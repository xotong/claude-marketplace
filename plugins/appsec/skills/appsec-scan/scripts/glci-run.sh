#!/usr/bin/env bash
# =============================================================================
# glci-run.sh — run ONE security category's real CI/CD catalog component job
# locally with GitLab's `glci` tool, and leave the report(s) at the same
# canonical paths the skill's docker engine (run-scan.sh) produces.
#
# Standalone: this script has no dependency on any other file in this skill.
# It is invoked directly; integration into run-scan.sh happens elsewhere.
#
# Interface is pinned — see scripts/glci-run.sh usage() below, and the task
# brief this was written against. Do not change flag names/shapes without
# updating whatever integrates this script.
# =============================================================================
set -euo pipefail

CATEGORY=""
COMPONENT=""
RESULTS_DIR=""
PROJECT_DIR=""
IMAGE_REF=""
DOCKERFILE_REL=""
INPUT_KEYS=()
INPUT_VALUES=()

error() { printf 'ERROR: %s\n' "$*" >&2; }

usage() {
  cat >&2 <<'EOF'
usage: glci-run.sh --category <secret_detection|container_scanning|dependency_scanning|sast> \
         --component <host/path/to/component@version> \
         --results <dir> --project-dir <dir> \
         [--input key=value]... \
         [--image <local image ref>] [--dockerfile <repo-relative path>]
EOF
}

# set_input <key> <value>: overrides an existing key in place (preserving its
# original position) or appends a new one. Used both for --input passthrough
# and for the forced/computed inputs (stage, cs_image, cs_dockerfile_path) so
# a caller-supplied --input can never fight the forced ones silently.
set_input() {
  local k=$1 v=$2 i
  for ((i = 0; i < ${#INPUT_KEYS[@]}; i++)); do
    if [ "${INPUT_KEYS[$i]}" = "$k" ]; then
      INPUT_VALUES[i]=$v
      return 0
    fi
  done
  INPUT_KEYS+=("$k")
  INPUT_VALUES+=("$v")
}

yaml_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  printf '%s' "$s"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --category)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      CATEGORY=$2; shift 2 ;;
    --component)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      COMPONENT=$2; shift 2 ;;
    --results)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      RESULTS_DIR=$2; shift 2 ;;
    --project-dir)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      PROJECT_DIR=$2; shift 2 ;;
    --image)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      IMAGE_REF=$2; shift 2 ;;
    --dockerfile)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      DOCKERFILE_REL=$2; shift 2 ;;
    --input)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      case "$2" in
        *=*) set_input "${2%%=*}" "${2#*=}" ;;
        *) error "--input needs key=value, got: $2"; usage; exit 2 ;;
      esac
      shift 2 ;;
    *)
      error "unknown argument: $1"
      usage
      exit 2 ;;
  esac
done

case "$CATEGORY" in
  secret_detection|container_scanning|dependency_scanning|sast) ;;
  "") error "--category is required"; usage; exit 2 ;;
  *) error "unknown category: $CATEGORY"; usage; exit 2 ;;
esac
[ -n "$COMPONENT" ] || { error "--component is required"; usage; exit 2; }
[ -n "$RESULTS_DIR" ] || { error "--results is required"; usage; exit 2; }
[ -n "$PROJECT_DIR" ] || { error "--project-dir is required"; usage; exit 2; }
case "$RESULTS_DIR" in
  /*) ;;
  *) error "--results must be an absolute path, got: $RESULTS_DIR"; usage; exit 2 ;;
esac

command -v python3 >/dev/null 2>&1 || {
  error "python3 is required to parse glci's JSON output but was not found on PATH"
  printf 'GLCI-RESULT: category=%s status=unavailable jobs= reports= glci_commit=\n' "$CATEGORY"
  printf 'GLCI-REASON: python3 not found on PATH\n'
  exit 3
}

# -----------------------------------------------------------------------------
# One embedded python3 helper, dispatched by subcommand, so this script stays
# a single file. JSON parsing (doctor health, glci's line-delimited events) is
# far more robust done here than by hand-rolled sed/grep on nested JSON.
#
# Written out to a real temp file (not `python3 - <<EOF`): the heredoc form
# consumes stdin to feed the script source, leaving nothing for the script's
# OWN stdin reads (doctor_health needs to read piped JSON on stdin).
# -----------------------------------------------------------------------------
# No ".py" suffix after the X run: BSD mktemp (macOS) only replaces a
# trailing run of X's, so a suffix after it comes back completely literal
# and unique-ified (silently reusing the same real file every invocation,
# then failing outright once two runs raced) — GNU mktemp handles a suffix
# fine, but this has to work on both.
PY_HELPER_FILE=$(mktemp "${TMPDIR:-/tmp}/glci-run-helper.XXXXXX")
trap 'rm -f "$PY_HELPER_FILE"' EXIT
cat >"$PY_HELPER_FILE" <<'PYEOF'
import json
import re
import sys

def doctor_health(_args):
    # "CI config" / "Git repository" fail outside a CI repo by design (a
    # pipeline file living under <results>/glci/ is not the project's own
    # .gitlab-ci.yml) and are ignored regardless of status.
    #
    # Every other check only blocks on a real "fail". "warn" is glci's own
    # signal that a check is fine as-is and does not need fixing before
    # `run` — real example: Daemon reports {"status":"warn","detail":"not
    # running (starts automatically on first use)"} on a cold environment,
    # which is exactly the "(or daemon auto-start)" case this script must
    # tolerate rather than bailing out to the docker engine over nothing.
    ignore = {"CI config", "Git repository"}
    try:
        data = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001 - report and fail closed
        print(f"glci doctor did not return valid JSON: {exc}")
        return 1
    for check in data.get("checks") or []:
        name = check.get("name", "")
        if name in ignore:
            continue
        if check.get("status") == "fail":
            detail = check.get("detail", "")
            print(f"{name}: {detail}".strip())
            return 1
    return 0

def parse_events(args):
    path = args[0]
    pipeline_id = ""
    jobs = {}  # job_name -> last status, insertion order preserved
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return 0
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not pipeline_id and event.get("pipeline_id") is not None:
                pipeline_id = str(event["pipeline_id"])
            if event.get("type") == "job_status":
                name = event.get("job_name")
                status = event.get("status")
                if name:
                    jobs[name] = status
    print(f"PID\t{pipeline_id}")
    for name, status in jobs.items():
        print(f"JOB\t{name}\t{status}")
    return 0

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NOISE_RE = re.compile(r"no matching files|no files to upload|uploading artifacts", re.IGNORECASE)
_MEANINGFUL_RE = re.compile(
    r"\[fata\]|\bfatal\b|\berror\b|\bfailed\b|denied|unauthorized|panic:|"
    r"\bcannot\b|no such|not enabled|not found",
    re.IGNORECASE,
)

def log_reason(args):
    path = args[0]
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        print("(job log unavailable)")
        return 0
    with fh:
        lines = [_ANSI_RE.sub("", ln).strip() for ln in fh]
    lines = [ln for ln in lines if ln]
    if not lines:
        print("(no log output)")
        return 0
    candidates = [ln for ln in lines if _MEANINGFUL_RE.search(ln) and not _NOISE_RE.search(ln)]
    chosen = candidates[-1] if candidates else lines[-1]
    print(chosen[:400])
    return 0

COMMANDS = {
    "doctor_health": doctor_health,
    "parse_events": parse_events,
    "log_reason": log_reason,
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("py_helper: unknown subcommand", file=sys.stderr)
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])

sys.exit(main())
PYEOF

py_helper() {
  python3 "$PY_HELPER_FILE" "$@"
}

# -----------------------------------------------------------------------------
# GLCI_BIN resolution: env override (path or PATH-relative name), else `glci`
# on PATH, else the default install location. Never network / never install.
#
# The caller's GLCI_BIN is captured into GLCI_BIN_OVERRIDE up front, before
# GLCI_BIN itself gets reused below to hold the RESOLVED absolute path — a
# same-named local reassignment would otherwise erase the override it is
# about to read.
# -----------------------------------------------------------------------------
GLCI_BIN_OVERRIDE="${GLCI_BIN:-}"
resolve_glci() {
  if [ -n "$GLCI_BIN_OVERRIDE" ]; then
    case "$GLCI_BIN_OVERRIDE" in
      */*)
        [ -x "$GLCI_BIN_OVERRIDE" ] && { printf '%s' "$GLCI_BIN_OVERRIDE"; return 0; }
        return 1 ;;
      *)
        command -v "$GLCI_BIN_OVERRIDE" 2>/dev/null && return 0
        return 1 ;;
    esac
  fi
  command -v glci 2>/dev/null && return 0
  if [ -x "${HOME:-/nonexistent}/.glci/bin/glci" ]; then
    printf '%s' "$HOME/.glci/bin/glci"
    return 0
  fi
  return 1
}

print_result() {
  # print_result <status> <jobs-csv> <reports-csv> <commit>
  printf 'GLCI-RESULT: category=%s status=%s jobs=%s reports=%s glci_commit=%s\n' \
    "$CATEGORY" "$1" "$2" "$3" "$4"
}

print_reason() {
  printf 'GLCI-REASON: %s\n' "$1"
}

fail_unavailable() {
  print_result unavailable "" "" ""
  print_reason "$1"
  exit 3
}

GLCI_BIN=""
if ! GLCI_BIN=$(resolve_glci); then
  fail_unavailable "glci not found (set GLCI_BIN, install to ~/.glci/bin/glci, or put it on PATH)"
fi

# Token/URL are passed ONLY as a per-invocation env prefix on the glci calls
# below (run_glci) — never exported script-wide, so no OTHER child process
# this script starts (python3, docker, unzip, git...) inherits them. Never on
# argv, never written to any file, never logged.
GITLAB_URL_VAL="${APPSEC_GITLAB_URL:-}"
GITLAB_TOKEN_VAL="${APPSEC_RESOLVED_TOKEN:-}"

run_glci() {
  GITLAB_URL="$GITLAB_URL_VAL" GITLAB_TOKEN="$GITLAB_TOKEN_VAL" "$GLCI_BIN" "$@"
}

# -----------------------------------------------------------------------------
# Health check BEFORE any container work (image push etc.) — no point pushing
# an image for a glci that cannot run at all. "CI config" / "Git repository"
# fail outside a CI repo by design; only real environment checks (Docker,
# glci images, Daemon, GitLab token, ...) gate us here.
# -----------------------------------------------------------------------------
DOCTOR_JSON=""
set +e
DOCTOR_JSON=$(cd "$PROJECT_DIR" 2>/dev/null && run_glci doctor --json 2>/dev/null)
set -e
DOCTOR_REASON=""
if ! DOCTOR_REASON=$(printf '%s' "$DOCTOR_JSON" | py_helper doctor_health); then
  fail_unavailable "glci doctor: ${DOCTOR_REASON:-unhealthy environment}"
fi

mkdir -p "$RESULTS_DIR/glci"
GLCI_DIR="$RESULTS_DIR/glci"
PIPELINE_FILE="$GLCI_DIR/$CATEGORY.gitlab-ci.yml"
EVENTS_FILE="$GLCI_DIR/$CATEGORY.events.jsonl"
RUN_STDERR_LOG="$GLCI_DIR/$CATEGORY.run-stderr.log"

BRANCH=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
[ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ] || BRANCH=main

read_registry_port() {
  # `docker port` legitimately exits non-zero whenever glci-mock does not
  # exist yet — neutralised with `|| true` before entering the pipe, or its
  # non-zero status becomes the pipeline's status under pipefail and set -e
  # aborts the whole script on the very first (expected) miss.
  port=$( (docker port glci-mock 2>/dev/null || true) | head -1 | sed -E 's#.*:([0-9]+)$#\1#')
  case "$port" in
    ''|*[!0-9]*) printf '' ;;
    *) printf '%s' "$port" ;;
  esac
}

# -----------------------------------------------------------------------------
# container_scanning: push the host-built image into glci's embedded registry
# so the component's cs_image input can reach it. Only when --image is given;
# a caller may also just pass --input cs_image=<already-reachable-ref>.
# -----------------------------------------------------------------------------
TRIVY_PLATFORM=""
if [ "$CATEGORY" = container_scanning ] && [ -n "$IMAGE_REF" ]; then
  run_glci daemon start >/dev/null 2>&1 || true

  REGISTRY_PORT=$(read_registry_port)
  if [ -z "$REGISTRY_PORT" ]; then
    # glci-mock (the embedded registry) is only brought up as a side effect
    # of an actual completed job run — `daemon start` alone starts only the
    # daemon process, verified empirically: `docker ps` shows no glci-mock
    # right after `daemon start`, only after a real `glci run` finishes a
    # job. One trivial throwaway job forces it up before the real pipeline
    # (which needs cs_image resolved from the port) is even written.
    WARMUP_PIPELINE="$GLCI_DIR/warmup.gitlab-ci.yml"
    printf 'stages: [test]\n\nwarmup:\n  stage: test\n  image: alpine:latest\n  script: ["true"]\n' \
      > "$WARMUP_PIPELINE"
    set +e
    ( cd "$PROJECT_DIR" && run_glci -f "$WARMUP_PIPELINE" run \
        --context "branch=$BRANCH" --no-token --secrets none --json ) \
      >"$GLCI_DIR/warmup.events.jsonl" 2>"$GLCI_DIR/warmup.run-stderr.log"
    set -e
  fi

  attempt=0
  while [ -z "$REGISTRY_PORT" ] && [ "$attempt" -lt 15 ]; do
    REGISTRY_PORT=$(read_registry_port)
    [ -n "$REGISTRY_PORT" ] && break
    sleep 1
    attempt=$((attempt + 1))
  done
  [ -n "$REGISTRY_PORT" ] || fail_unavailable "glci-mock embedded registry did not publish a port after warmup + 15s"

  last_segment=${IMAGE_REF##*/}
  if [ "$last_segment" != "${last_segment%:*}" ]; then
    local_tag=${last_segment##*:}
    local_name=${last_segment%:*}
  else
    local_tag=latest
    local_name=$last_segment
  fi
  local_name=$(printf '%s' "$local_name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')
  local_tag=$(printf '%s' "$local_tag" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')

  HOST_PUSH_REF="127.0.0.1:${REGISTRY_PORT}/appsec/${local_name}:${local_tag}"
  JOB_VISIBLE_REF="glci-mock:${REGISTRY_PORT}/appsec/${local_name}:${local_tag}"

  docker tag "$IMAGE_REF" "$HOST_PUSH_REF" || fail_unavailable "docker tag failed for $IMAGE_REF"
  docker push "$HOST_PUSH_REF" >/dev/null 2>&1 || fail_unavailable "docker push to glci's embedded registry failed for $HOST_PUSH_REF"

  TRIVY_PLATFORM=$(docker image inspect "$IMAGE_REF" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || true)
  set_input cs_image "$JOB_VISIBLE_REF"
fi
if [ "$CATEGORY" = container_scanning ] && [ -n "$DOCKERFILE_REL" ]; then
  set_input cs_dockerfile_path "$DOCKERFILE_REL"
fi

# stage: test is always forced, last, so nothing above (or any --input) can
# quietly override it — see the "glci facts" note on orphaned stages.
set_input stage test

{
  printf 'stages: [test]\n\n'
  printf 'include:\n'
  printf '  - component: %s\n' "$COMPONENT"
  printf '    inputs:\n'
  for ((i = 0; i < ${#INPUT_KEYS[@]}; i++)); do
    printf '      %s: "%s"\n' "${INPUT_KEYS[$i]}" "$(yaml_escape "${INPUT_VALUES[$i]}")"
  done
} > "$PIPELINE_FILE"

RUN_ARGS=(-f "$PIPELINE_FILE" run --context "branch=$BRANCH" --no-token --secrets none --json)
if [ "$CATEGORY" = container_scanning ] && [ -n "$IMAGE_REF" ]; then
  RUN_ARGS+=(--env CS_REGISTRY_INSECURE=true)
  [ -z "$TRIVY_PLATFORM" ] || RUN_ARGS+=(--env "TRIVY_PLATFORM=$TRIVY_PLATFORM")
fi
# Without this the component fatals "dependency scanning feature not
# enabled" — it gates on GITLAB_FEATURES the same way the docker engine's
# runner (scanners/gitlab-dependency-scanning.sh) already forces it.
if [ "$CATEGORY" = dependency_scanning ]; then
  RUN_ARGS+=(--env GITLAB_FEATURES=dependency_scanning)
fi

set +e
( cd "$PROJECT_DIR" && run_glci "${RUN_ARGS[@]}" ) >"$EVENTS_FILE" 2>"$RUN_STDERR_LOG"
set -e

# `glci version` writes to stderr, not stdout. Captured into a variable
# first (not piped straight into awk): an awk `exit` on the first match
# closes its end of a live pipe early, SIGPIPEs `glci version`, and under
# pipefail + set -e that silently kills this whole script.
GLCI_VERSION_OUT=$(run_glci version 2>&1 >/dev/null || true)
GLCI_COMMIT=$(printf '%s\n' "$GLCI_VERSION_OUT" | awk '/^glci/{for(i=1;i<=NF;i++) if($i=="commit") print $(i+1)}')

# -----------------------------------------------------------------------------
# Parse events -> job:status map. Judge each job, never the pipeline outcome
# (components set allow_failure: true, so "pipeline passed" proves nothing).
# -----------------------------------------------------------------------------
PARSED=$(py_helper parse_events "$EVENTS_FILE")
PIPELINE_ID=""
JOB_NAMES=()
JOB_STATUSES=()
while IFS=$'\t' read -r tag a b; do
  case "$tag" in
    PID) PIPELINE_ID=$a ;;
    JOB) JOB_NAMES+=("$a"); JOB_STATUSES+=("$b") ;;
  esac
done <<PARSED_EOF
$PARSED
PARSED_EOF

if [ "${#JOB_NAMES[@]}" -eq 0 ]; then
  # Under pipefail, `grep -v` matching nothing (an all-blank/empty log) exits
  # 1 and would otherwise abort this whole script via set -e here — the same
  # class of bug as the `glci version | awk` SIGPIPE above, just via a
  # legitimate empty-match instead of a signal. `|| true` keeps it a plain
  # "no reason found" instead of a silent death.
  reason=$( (tail -n 5 "$RUN_STDERR_LOG" 2>/dev/null | grep -v '^[[:space:]]*$' || true) | tail -n 1)
  print_result no_report "" "" "$GLCI_COMMIT"
  print_reason "${reason:-glci run produced no job events; see $RUN_STDERR_LOG}"
  exit 4
fi

jobs_csv=""
for ((i = 0; i < ${#JOB_NAMES[@]}; i++)); do
  entry="${JOB_NAMES[$i]}:${JOB_STATUSES[$i]}"
  jobs_csv=${jobs_csv:+$jobs_csv,}$entry
done

# Fetch every job's trace log up front — needed for the failure reason and
# harmless (and useful) even on a clean pass.
for ((i = 0; i < ${#JOB_NAMES[@]}; i++)); do
  job=${JOB_NAMES[$i]}
  set +e
  run_glci log "$PIPELINE_ID" "$job" >"$GLCI_DIR/$CATEGORY.$job.log" 2>&1
  set -e
done

FAILED_JOB=""
for ((i = 0; i < ${#JOB_NAMES[@]}; i++)); do
  if [ "${JOB_STATUSES[$i]}" != passed ]; then
    FAILED_JOB=${JOB_NAMES[$i]}
    break
  fi
done

if [ -n "$FAILED_JOB" ]; then
  reason=$(py_helper log_reason "$GLCI_DIR/$CATEGORY.$FAILED_JOB.log")
  print_result job_failed "$jobs_csv" "" "$GLCI_COMMIT"
  print_reason "$reason"
  exit 4
fi

# -----------------------------------------------------------------------------
# Every job passed: pull each job's artifacts, unzip under <results>/glci/,
# and copy ONLY the category's primary report(s) to the canonical top-level
# path(s) the docker engine (run-scan.sh) writes. Everything else stays under
# glci/ so it is not misread as evidence by normalize.py (which needs "glci"
# added to its bin/catalog skip list — this script does not touch normalize.py).
# -----------------------------------------------------------------------------
mkdir -p "$GLCI_DIR/$CATEGORY"
COPIED_REPORTS=()

# copy_one_report <glob> <dest-basename>: copy the first file matching <glob>
# under the current iteration's job_dir to $RESULTS_DIR/<dest-basename> and
# record it in COPIED_REPORTS. A no-op when nothing matches.
copy_one_report() {
  local glob=$1 dest=$2 found
  found=$(find "$job_dir" -name "$glob" -print -quit 2>/dev/null)
  if [ -n "$found" ]; then
    cp "$found" "$RESULTS_DIR/$dest"
    COPIED_REPORTS+=("$dest")
  fi
}

for ((i = 0; i < ${#JOB_NAMES[@]}; i++)); do
  job=${JOB_NAMES[$i]}
  zip_path="$GLCI_DIR/$CATEGORY/$job.zip"
  job_dir="$GLCI_DIR/$CATEGORY/$job"
  set +e
  run_glci artifacts download "$job" -o "$zip_path" >/dev/null 2>&1
  set -e
  [ -f "$zip_path" ] || continue
  rm -rf "$job_dir"
  mkdir -p "$job_dir"
  unzip -oq "$zip_path" -d "$job_dir" 2>/dev/null || true
  rm -f "$zip_path"

  case "$CATEGORY" in
    secret_detection)
      copy_one_report 'gl-secret-detection-report.json' gl-secret-detection-report.json
      ;;
    container_scanning)
      # Deliberately NOT copying gl-sbom-*.cdx.json here: GTCS writes an
      # image SBOM under the same glob dependency_scanning uses, and copying
      # it to the results top level would be misattributed as dependency
      # evidence by normalize.py's rglob (see run-scan.sh's own comment on
      # clear_stale_reports/container_scanning for the same rule applied to
      # deletion). It stays inside job_dir / glci/ only.
      copy_one_report 'gl-container-scanning-report.json' gl-container-scanning-report.json
      ;;
    dependency_scanning)
      while IFS= read -r sbom; do
        [ -n "$sbom" ] || continue
        base=$(basename "$sbom")
        cp "$sbom" "$RESULTS_DIR/$base"
        COPIED_REPORTS+=("$base")
      done < <(find "$job_dir" -name 'gl-sbom-*.cdx.json' 2>/dev/null)
      copy_one_report 'gl-dependency-scanning-report.json' gl-dependency-scanning-report.json
      ;;
    sast)
      # The real CI component's declared artifact is gl-sast-report.json
      # (scanners/fortify-sast.contract: report.sast=gl-sast-report.json) —
      # a converted GitLab SAST JSON report, NOT the raw .fpr project file
      # run-scan.sh's docker engine names fortify-sast.fpr. Those are two
      # different formats from two different Fortify invocations; forcing
      # this JSON into a *.fpr-named file would be actively wrong, so it is
      # copied under its real name instead. Flagged in the task report as
      # something the integrator must decide on explicitly.
      copy_one_report 'gl-sast-report.json' gl-sast-report.json
      ;;
  esac
done

if [ "${#COPIED_REPORTS[@]}" -eq 0 ]; then
  print_result no_report "$jobs_csv" "" "$GLCI_COMMIT"
  print_reason "every job passed but no expected report was found in its artifacts (see $GLCI_DIR/$CATEGORY/<job>/)"
  exit 4
fi

reports_csv=""
for r in "${COPIED_REPORTS[@]}"; do
  reports_csv=${reports_csv:+$reports_csv,}$r
done

print_result ok "$jobs_csv" "$reports_csv" "$GLCI_COMMIT"
exit 0

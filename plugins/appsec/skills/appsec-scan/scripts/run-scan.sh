#!/usr/bin/env bash
set -euo pipefail

ONLY_CATEGORY=
DRY_RUN=false
RAN_CATEGORIES=
EXECUTED_CATEGORIES=
DS_RAN=false
SKIPPED_IMAGE_SCANNERS=

info() { printf 'INFO: %s\n' "$*" >&2; }
warning() { printf 'WARNING: %s\n' "$*" >&2; }
error() { printf 'ERROR: %s\n' "$*" >&2; }

usage() {
  error "usage: run-scan.sh [--only <category>] [--dry-run]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --only)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      ONLY_CATEGORY=$2
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

case "$ONLY_CATEGORY" in
  ""|sast|dependency_scanning|secret_detection|container_scanning) ;;
  *) error "unknown category: $ONLY_CATEGORY"; exit 2 ;;
esac

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SKILL_DIR="${SKILL_DIR:-$(dirname "$SCRIPTS_DIR")}"
SCANNERS_DIR="${SCANNERS_DIR:-$SKILL_DIR/scanners}"

if [ -z "${RUN_FORTIFY_SAST+x}" ] && \
   [ -z "${RUN_GITLAB_DS+x}" ] && \
   [ -z "${RUN_SECRET_DETECTION+x}" ] && \
   [ -z "${RUN_GITLAB_CS+x}" ]; then
  echo '[run-scan] RUN_* vars absent, self-loading preferences...' >&2
  eval "$(bash "$SCRIPTS_DIR/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml")"
fi

# load-prefs.sh never emits RUNTIME — it comes from detect-runtime.sh, which
# SKILL.md Step 1.5 exports. Standalone invocations (Step 5's `--only` rescan,
# or anyone taking "safe to re-run independently" at its word) previously died
# with "required environment variables are unset: RUNTIME". Detect it here.
if [ -z "${RUNTIME:-}" ]; then
  RUNTIME="$(CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-auto}" bash "$SCRIPTS_DIR/detect-runtime.sh")" || {
    echo 'ERROR: no usable container runtime; start docker or podman and retry' >&2
    exit 2
  }
  export RUNTIME
fi

validate_env() {
  missing=
  for name in RUNTIME APPSEC_PROFILE; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || missing="$missing $name"
  done
  if [ -n "$missing" ]; then
    error "required environment variables are unset:$missing"
    exit 2
  fi
}

selected() {
  [ -z "$ONLY_CATEGORY" ] || [ "$ONLY_CATEGORY" = "$1" ]
}

# mark_executed: a scanner actually launched. Distinct from mark_attempted,
# which records what the admin config EXPECTS. Conflating the two killed the
# "no scanners ran" diagnostic, because the expected set is never empty.
mark_executed() {
  case ",$EXECUTED_CATEGORIES," in
    *",$1,"*) return ;;
  esac
  if [ -n "$EXECUTED_CATEGORIES" ]; then
    EXECUTED_CATEGORIES="$EXECUTED_CATEGORIES,$1"
  else
    EXECUTED_CATEGORIES=$1
  fi
}

mark_attempted() {
  case ",$RAN_CATEGORIES," in
    *",$1,"*) return ;;
  esac
  if [ -n "$RAN_CATEGORIES" ]; then
    RAN_CATEGORIES="$RAN_CATEGORIES,$1"
  else
    RAN_CATEGORIES=$1
  fi
}

record_missing_image() {
  warning "[$1] Enabled but $2 is empty; skipping scanner"
  if [ -n "${3:-}" ]; then
    record_skip "$3" "$1 is enabled but its image ($2) is empty in scanner-preferences.yaml, so it did NOT run. Set the image for this category and re-run this skill."
  fi
  if [ -n "$SKIPPED_IMAGE_SCANNERS" ]; then
    SKIPPED_IMAGE_SCANNERS="$SKIPPED_IMAGE_SCANNERS,$1"
  else
    SKIPPED_IMAGE_SCANNERS=$1
  fi
}

is_sensitive_env_name() {
  case "$1" in
    *[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]*|\
    *[Tt][Oo][Kk][Ee][Nn]*|\
    *[Ss][Ee][Cc][Rr][Ee][Tt]*|\
    *[Kk][Ee][Yy]*|\
    *[Cc][Rr][Ee][Dd][Ee][Nn][Tt][Ii][Aa][Ll]*|\
    CS_REGISTRY_USER|ARTIFACTORY_USER) return 0 ;;
  esac
  return 1
}

print_dry_run() {
  printf 'DRY-RUN:'
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "-e" ] && [ "$#" -ge 2 ]; then
      printf ' %q' "$1"
      shift
      env_name=${1%%=*}
      if [ "$env_name" != "$1" ] && is_sensitive_env_name "$env_name"; then
        printf ' %q=***' "$env_name"
      else
        printf ' %q' "$1"
      fi
    else
      printf ' %q' "$1"
    fi
    shift
  done
  printf '\n'
}

run_cmd() {
  if $DRY_RUN; then
    print_dry_run "$@"
    return 0
  fi
  "$@"
}

start_watchdog() {
  scanner_pid=$1
  watchdog_timeout=${APPSEC_SCAN_TIMEOUT:-3600}
  case "$watchdog_timeout" in
    ''|*[!0-9]*) watchdog_timeout=3600 ;;
  esac
  # ponytail: APPSEC_SCAN_TIMEOUT defaults to a 3600-second per-scanner ceiling.
  # Only the scanner PID is portable here, so grandchildren may survive; launching
  # parallel scanners under setsid would upgrade cleanup to the full process group.
  (
    watchdog_started=$SECONDS
    while kill -0 "$scanner_pid" 2>/dev/null; do
      if [ $((SECONDS - watchdog_started)) -ge "$watchdog_timeout" ]; then
        kill -TERM "$scanner_pid" 2>/dev/null || true
        sleep 2
        if kill -0 "$scanner_pid" 2>/dev/null; then
          kill -KILL "$scanner_pid" 2>/dev/null || true
        fi
        break
      fi
      # ponytail: 0.25s poll so a finished scanner is reaped promptly (fractional
      # sleep is supported on macOS/Linux/WSL/Git-Bash); coarser only saves CPU on
      # scans that already run for minutes.
      sleep 0.25
    done
  ) </dev/null >/dev/null 2>&1 &
  WATCHDOG_PID=$!
}

run_container_scan() {
  container_log=$1
  shift
  container_timeout=${APPSEC_SCAN_TIMEOUT:-3600}
  case "$container_timeout" in
    ''|*[!0-9]*)
      warning "Invalid APPSEC_SCAN_TIMEOUT '$container_timeout'; using 3600 seconds"
      container_timeout=3600
      ;;
  esac

  container_process_group=false
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" >"$container_log" 2>&1 &
    container_pid=$!
    container_process_group=true
  else
    "$@" >"$container_log" 2>&1 &
    container_pid=$!
  fi

  # ponytail: the default 3600-second ceiling can only terminate the runtime PID
  # on macOS/Bash 3.2; installing setsid upgrades cleanup to the full process group.
  container_started=$SECONDS
  container_timed_out=false
  while kill -0 "$container_pid" 2>/dev/null; do
    if [ $((SECONDS - container_started)) -ge "$container_timeout" ]; then
      container_timed_out=true
      warning "Container scan timed out after ${container_timeout}s; terminating it"
      if $container_process_group; then
        kill -TERM -- "-$container_pid" 2>/dev/null || true
      else
        kill -TERM "$container_pid" 2>/dev/null || true
      fi
      sleep 2
      if $container_process_group; then
        if kill -0 -- "-$container_pid" 2>/dev/null; then
          kill -KILL -- "-$container_pid" 2>/dev/null || true
        fi
      else
        if kill -0 "$container_pid" 2>/dev/null; then
          kill -KILL "$container_pid" 2>/dev/null || true
        fi
      fi
      break
    fi
    sleep 1
  done

  if wait "$container_pid"; then
    container_rc=0
  else
    container_rc=$?
  fi
  cat "$container_log"
  if $container_timed_out; then
    return 124
  fi
  return "$container_rc"
}

validate_env

RUN_FORTIFY_SAST="${RUN_FORTIFY_SAST:-false}"
RUN_GITLAB_DS="${RUN_GITLAB_DS:-false}"
RUN_SECRET_DETECTION="${RUN_SECRET_DETECTION:-false}"
RUN_GITLAB_CS="${RUN_GITLAB_CS:-false}"

if [ "$RUN_FORTIFY_SAST" = false ] && \
   [ "$RUN_GITLAB_DS" = false ] && \
   [ "$RUN_SECRET_DETECTION" = false ] && \
   [ "$RUN_GITLAB_CS" = false ]; then
  warning "no scanners enabled — check scanner-preferences.yaml or set RUN_* vars"
  exit 2
fi

FORTIFY_SAST_IMAGE="${FORTIFY_SAST_IMAGE:-}"
GITLAB_DS_IMAGE="${GITLAB_DS_IMAGE:-}"
SECRET_DETECTION_IMAGE="${SECRET_DETECTION_IMAGE:-}"
GITLAB_CS_IMAGE="${GITLAB_CS_IMAGE:-}"
CS_USER_ENV="${CS_USER_ENV:-CS_REGISTRY_USER}"
CS_PASS_ENV="${CS_PASS_ENV:-CS_REGISTRY_PASSWORD}"

mkdir -p .appsec-results
# Self-ignoring output dir: the "add .appsec-results/ to .gitignore"
# reminder enforces nothing, and this directory holds the raw secret
# detection report. A .gitignore of "*" inside it keeps git away without
# editing the project's own .gitignore.
printf '*\n' > .appsec-results/.gitignore
SKIPS_FILE=.appsec-results/scan-skips
: >"$SKIPS_FILE"

# record_skip <category> <actionable reason shown to the user>
record_skip() {
  printf '%s\t%s\n' "$1" "$2" >>"$SKIPS_FILE"
}

if selected sast && [ "$RUN_FORTIFY_SAST" = true ] && [ -z "$FORTIFY_SAST_IMAGE" ]; then
  record_missing_image "Fortify SCA" FORTIFY_SAST_IMAGE sast
fi
if selected dependency_scanning && [ "$RUN_GITLAB_DS" = true ] && [ -z "$GITLAB_DS_IMAGE" ]; then
  record_missing_image "GitLab DS" GITLAB_DS_IMAGE dependency_scanning
fi
if selected secret_detection && [ "$RUN_SECRET_DETECTION" = true ] && [ -z "$SECRET_DETECTION_IMAGE" ]; then
  record_missing_image "Secret Detection" SECRET_DETECTION_IMAGE secret_detection
fi
if selected container_scanning && [ "$RUN_GITLAB_CS" = true ] && [ -z "$GITLAB_CS_IMAGE" ]; then
  record_missing_image "GitLab CS" GITLAB_CS_IMAGE container_scanning
fi

# Every ENABLED category is expected to produce a report, marked BEFORE any
# per-category precondition can bail out.
#
# This used to be marked inside each scanner's success path, so a category that
# bailed early was neither "ran" nor "missing" — it vanished from
# scan-coverage.json entirely. A Go repo with no Dockerfile therefore reported
# "Gate verdict: PASSED", exit 0, with SAST and container scanning never run and
# no warning at all: the exact false all-clear SKILL.md promises cannot happen.
# Expect-first makes the guarantee uniform — anything without a report becomes a
# coverage finding, whatever the reason it did not run.
# Expectation comes from the ADMIN CONFIG, never from this invocation.
#
# Deriving it from the RUN_* environment meant a single leftover
# `export RUN_SECRET_DETECTION=true` suppressed the self-load block above, the
# other three flags silently defaulted to false, and the run reported
# "Gate verdict: PASSED" / exit 0 with three admin-enabled categories absent
# from scan-coverage.json entirely — no warning anywhere. Deriving it from
# --only had the same effect on a first scoped scan.
#
# --only and the RUN_* env narrow what EXECUTES. They must never narrow what is
# EXPECTED, or a scan can silently cover less than the admin configured.
config_flags=$(bash "$SCRIPTS_DIR/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml" 2>/dev/null || true)
for pair in \
  "RUN_FORTIFY_SAST sast" \
  "RUN_GITLAB_DS dependency_scanning" \
  "RUN_SECRET_DETECTION secret_detection" \
  "RUN_GITLAB_CS container_scanning"; do
  flag=${pair%% *}
  category=${pair##* }
  if printf '%s\n' "$config_flags" | grep -qx "export $flag=true"; then
    mark_attempted "$category"
  fi
done
# Fall back to the live flags if the config could not be read at all, so a
# broken config degrades to the old behaviour instead of expecting nothing.
if [ -z "$RAN_CATEGORIES" ]; then
  if [ "$RUN_FORTIFY_SAST" = true ]; then mark_attempted sast; fi
  if [ "$RUN_GITLAB_DS" = true ]; then mark_attempted dependency_scanning; fi
  if [ "$RUN_SECRET_DETECTION" = true ]; then mark_attempted secret_detection; fi
  if [ "$RUN_GITLAB_CS" = true ]; then mark_attempted container_scanning; fi
fi

APP_NAME="${APP_NAME:-$(basename "$PWD")}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SOURCE_PATH="${SOURCE_PATH:-src}"

FORTIFY_SAST_PID=
FORTIFY_SAST_WATCHDOG=
GITLAB_DS_PID=
GITLAB_DS_WATCHDOG=
SECRET_DETECTION_PID=
SECRET_DETECTION_WATCHDOG=
GITLAB_CS_PID=

HAS_POM=false
HAS_GRADLE=false
HAS_PACKAGE_JSON=false
HAS_REQUIREMENTS=false
HAS_DOCKERFILE=false
[ -f pom.xml ] && HAS_POM=true
{ [ -f build.gradle ] || [ -f build.gradle.kts ]; } && HAS_GRADLE=true
[ -f package.json ] && HAS_PACKAGE_JSON=true
{ [ -f requirements.txt ] || [ -f pyproject.toml ]; } && HAS_REQUIREMENTS=true
[ -f Dockerfile ] && HAS_DOCKERFILE=true
HAS_POM_NO_GRADLE=false
{ $HAS_POM && ! $HAS_GRADLE; } && HAS_POM_NO_GRADLE=true

info "Project: $APP_NAME  Branch: $BRANCH"
info "Detected: Maven=$HAS_POM Gradle=$HAS_GRADLE NPM=$HAS_PACKAGE_JSON Python=$HAS_REQUIREMENTS Dockerfile=$HAS_DOCKERFILE HAS_POM_NO_GRADLE=$HAS_POM_NO_GRADLE"
mkdir -p .appsec-results
grep -qxF '.appsec-results/' .gitignore 2>/dev/null || \
  info "Reminder: add .appsec-results/ to .gitignore"

# ponytail: RUN_* values are data; only the literal string true enables a scanner.
if selected sast && [ "$RUN_FORTIFY_SAST" = true ] && [ -n "$FORTIFY_SAST_IMAGE" ]; then
  if [ -z "${FORTIFY_LANGUAGE:-}" ]; then
    if $HAS_GRADLE; then FORTIFY_LANGUAGE=gradle
    elif $HAS_POM; then FORTIFY_LANGUAGE=maven
    elif $HAS_REQUIREMENTS; then FORTIFY_LANGUAGE=python
    elif $HAS_PACKAGE_JSON; then FORTIFY_LANGUAGE=javascript
    else
      info "[Fortify SCA] No supported project type detected; skipping"
      record_skip sast "Fortify found no supported project type (maven/gradle/python/javascript), so SAST did NOT run and your source was never analysed. Set FORTIFY_LANGUAGE explicitly, or add the matching build manifest, then re-run this skill."
      RUN_FORTIFY_SAST=false
    fi
  fi
  if [ "$RUN_FORTIFY_SAST" = true ]; then
    mark_attempted sast
    mark_executed sast
    info "[Fortify SCA] Pulling ${FORTIFY_SAST_IMAGE}..."
    if run_cmd "$RUNTIME" pull "${FORTIFY_SAST_IMAGE}"; then
      if $DRY_RUN; then
        print_dry_run "$RUNTIME" run --rm -v "$PWD:/workspace" -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" -w /workspace -e APP_NAME="$APP_NAME" -e SOURCE_PATH="$SOURCE_PATH" -e FORTIFY_LANGUAGE="$FORTIFY_LANGUAGE" -e MAVEN_SETTINGS="${MAVEN_SETTINGS:-}" -e ARTIFACTORY_USER="${ARTIFACTORY_USER:-}" -e ARTIFACTORY_PASSWORD="${ARTIFACTORY_PASSWORD:-}" "${FORTIFY_SAST_IMAGE}" sh /runner.sh
      else
        "$RUNTIME" run --rm \
          -v "$PWD:/workspace" \
          -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" \
          -w /workspace \
          -e APP_NAME="$APP_NAME" \
          -e SOURCE_PATH="$SOURCE_PATH" \
          -e FORTIFY_LANGUAGE="$FORTIFY_LANGUAGE" \
          -e MAVEN_SETTINGS="${MAVEN_SETTINGS:-}" \
          -e ARTIFACTORY_USER="${ARTIFACTORY_USER:-}" \
          -e ARTIFACTORY_PASSWORD="${ARTIFACTORY_PASSWORD:-}" \
          "${FORTIFY_SAST_IMAGE}" \
          sh /runner.sh > .appsec-results/fortify-sast.log 2>&1 &
        FORTIFY_SAST_PID=$!
        start_watchdog "$FORTIFY_SAST_PID"
        FORTIFY_SAST_WATCHDOG=$WATCHDOG_PID
      fi
    else
      warning "[Fortify SCA] Failed to pull ${FORTIFY_SAST_IMAGE}; skipping scan"
      record_skip sast "Could not pull ${FORTIFY_SAST_IMAGE}, so SAST did NOT run and your source was never analysed. Log in to the registry (docker login <registry-host>) or fix the image path in scanner-preferences.yaml, then re-run this skill."
    fi
  fi
fi

if selected dependency_scanning && [ "$RUN_GITLAB_DS" = true ] && [ -n "$GITLAB_DS_IMAGE" ]; then
  DS_RAN=true
  mark_attempted dependency_scanning
  mark_executed dependency_scanning
  info "[GitLab DS] Pulling ${GITLAB_DS_IMAGE}..."
  if run_cmd "$RUNTIME" pull "${GITLAB_DS_IMAGE}"; then
    if $DRY_RUN; then
      print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-dependency-scanning.sh:/runner.sh:ro" -w /workspace -e CI_PROJECT_DIR=/workspace -e GITLAB_FEATURES=dependency_scanning "${GITLAB_DS_IMAGE}" sh /runner.sh
    else
      "$RUNTIME" run --rm \
        --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/gitlab-dependency-scanning.sh:/runner.sh:ro" \
        -w /workspace \
        -e CI_PROJECT_DIR="/workspace" \
        -e GITLAB_FEATURES="dependency_scanning" \
        "${GITLAB_DS_IMAGE}" \
        sh /runner.sh > .appsec-results/gitlab-ds.log 2>&1 &
      GITLAB_DS_PID=$!
      start_watchdog "$GITLAB_DS_PID"
      GITLAB_DS_WATCHDOG=$WATCHDOG_PID
    fi
  else
    warning "[GitLab DS] Failed to pull ${GITLAB_DS_IMAGE}; skipping scan"
    record_skip dependency_scanning "Could not pull ${GITLAB_DS_IMAGE}, so dependency scanning did NOT run. Log in to the registry or fix the image path in scanner-preferences.yaml, then re-run this skill."
  fi
fi

if selected secret_detection && [ "$RUN_SECRET_DETECTION" = true ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ -n "$SECRET_DETECTION_IMAGE" ]; then
  mark_attempted secret_detection
  mark_executed secret_detection
  info "[Secret Detection] Pulling ${SECRET_DETECTION_IMAGE}..."
  if run_cmd "$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"; then
    if $DRY_RUN; then
      print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/secret-detection.sh:/runner.sh:ro" -w /workspace -e CI_PROJECT_DIR=/workspace -e GIT_DEPTH="${GIT_DEPTH:-50}" -e SECRET_DETECTION_EXCLUDED_PATHS="${SECRET_DETECTION_EXCLUDED_PATHS:-}" "${SECRET_DETECTION_IMAGE}" sh /runner.sh
    else
      "$RUNTIME" run --rm \
        --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/secret-detection.sh:/runner.sh:ro" \
        -w /workspace \
        -e CI_PROJECT_DIR="/workspace" \
        -e GIT_DEPTH="${GIT_DEPTH:-50}" \
        -e SECRET_DETECTION_EXCLUDED_PATHS="${SECRET_DETECTION_EXCLUDED_PATHS:-}" \
        "${SECRET_DETECTION_IMAGE}" \
        sh /runner.sh > .appsec-results/secret-detection.log 2>&1 &
      SECRET_DETECTION_PID=$!
      start_watchdog "$SECRET_DETECTION_PID"
      SECRET_DETECTION_WATCHDOG=$WATCHDOG_PID
    fi
  else
    warning "[Secret Detection] Failed to pull ${SECRET_DETECTION_IMAGE}; skipping scan"
    record_skip secret_detection "Could not pull ${SECRET_DETECTION_IMAGE}, so secret detection did NOT run. Log in to the registry or fix the image path in scanner-preferences.yaml, then re-run this skill."
  fi
elif selected secret_detection && [ "$RUN_SECRET_DETECTION" = true ]; then
  info "[Secret Detection] Skipped — not a Git worktree or image unset"
  record_skip secret_detection "Secret detection needs a Git worktree (it scans history), and this directory is not one — or its image is unset. Run the scan from inside the repository, then re-run this skill."
fi

if ! $DRY_RUN; then
  info "Waiting for parallel scanners..."
  for pid_var in FORTIFY_SAST_PID GITLAB_DS_PID SECRET_DETECTION_PID; do
    pid="${!pid_var:-}"
    if [ -n "$pid" ]; then
      if wait "$pid"; then
        info "[${pid_var/_PID/}] Done"
      else
        rc=$?
        if [ "$pid_var" = "GITLAB_DS_PID" ] && [ "$rc" -eq 2 ]; then
          warning "[GITLAB_DS] Local run unsupported by this analyzer — run Dependency Scanning in the CI pipeline"
        else
          warning "[${pid_var/_PID/}] Failed — check .appsec-results/ for logs"
        fi
      fi
      watchdog_var="${pid_var%_PID}_WATCHDOG"
      watchdog_pid="${!watchdog_var:-}"
      [ -z "$watchdog_pid" ] || wait "$watchdog_pid" 2>/dev/null || true
    fi
  done

  # The analyzer exits 0 when it simply finds no lock file, so a non-zero rc is
  # not the signal — the absence of a report is. Name the real cause instead of
  # leaving the generic "expected a report and did not" text.
  if [ -n "${GITLAB_DS_PID:-}" ] && ! ls .appsec-results/gl-sbom-*.cdx.json >/dev/null 2>&1 \
     && [ ! -s .appsec-results/gl-dependency-scanning-report.json ]; then
    record_skip dependency_scanning "The dependency analyzer produced no SBOM: it needs a lock file (package-lock.json, poetry.lock, a pip-compile requirements lock, go.sum...), not a plain manifest. Add one and re-run this skill, or rely on the CI pipeline for this category. Details: .appsec-results/gitlab-ds.log"
  fi
fi

if selected container_scanning && [ "$RUN_GITLAB_CS" = true ] && [ -n "$GITLAB_CS_IMAGE" ]; then
  if $DRY_RUN; then
    print_dry_run bash "$SCRIPTS_DIR/container-target.sh" "$RUNTIME" "$APP_NAME" .appsec-results
    if [ -n "${CS_IMAGE:-}" ]; then
      CS_TARGET="registry|${CS_IMAGE}"
    elif $HAS_DOCKERFILE; then
      CS_TARGET="archive|.appsec-results/container-image.tar"
    else
      CS_TARGET="none|"
    fi
  else
    CS_TARGET="$(bash "$SCRIPTS_DIR/container-target.sh" "$RUNTIME" "$APP_NAME" ".appsec-results" || true)"
  fi
  CS_MODE="${CS_TARGET%%|*}"
  CS_VALUE="${CS_TARGET#*|}"
  case "$CS_MODE" in
    registry)
      mark_attempted container_scanning
      mark_executed container_scanning
      info "[GitLab CS] Scanning registry image $CS_VALUE..."
      if run_cmd "$RUNTIME" pull "${GITLAB_CS_IMAGE}"; then
        if $DRY_RUN; then
          print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" -w /workspace -e CI_PROJECT_DIR=/workspace -e CS_SCAN_MODE=registry -e CS_IMAGE="$CS_VALUE" -e CS_REGISTRY_USER="$(printenv "$CS_USER_ENV" 2>/dev/null || true)" -e CS_REGISTRY_PASSWORD="$(printenv "$CS_PASS_ENV" 2>/dev/null || true)" "${GITLAB_CS_IMAGE}" sh /runner.sh
        elif run_container_scan .appsec-results/gitlab-cs.log "$RUNTIME" run --rm --entrypoint "" \
          -v "$PWD:/workspace" \
          -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
          -w /workspace \
          -e CI_PROJECT_DIR="/workspace" \
          -e CS_SCAN_MODE="registry" \
          -e CS_IMAGE="$CS_VALUE" \
          -e CS_REGISTRY_USER="$(printenv "$CS_USER_ENV" 2>/dev/null || true)" \
          -e CS_REGISTRY_PASSWORD="$(printenv "$CS_PASS_ENV" 2>/dev/null || true)" \
          "${GITLAB_CS_IMAGE}" \
          sh /runner.sh; then
          GITLAB_CS_PID="ran"
        else
          warning "[GitLab CS] Scan failed — check .appsec-results/gitlab-cs.log"
        fi
      else
        warning "[GitLab CS] Failed to pull ${GITLAB_CS_IMAGE}; skipping scan"
        record_skip container_scanning "Could not pull ${GITLAB_CS_IMAGE}, so container scanning did NOT run. Log in to the registry or fix the image path in scanner-preferences.yaml, then re-run this skill."
      fi
      ;;
    archive)
      mark_attempted container_scanning
      mark_executed container_scanning
      info "[GitLab CS] Scanning locally-built image (offline, bundled Trivy)..."
      if run_cmd "$RUNTIME" pull "${GITLAB_CS_IMAGE}"; then
        if $DRY_RUN; then
          print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" -w /workspace -e CI_PROJECT_DIR=/workspace -e CS_SCAN_MODE=archive -e CS_ARCHIVE=/workspace/.appsec-results/container-image.tar "${GITLAB_CS_IMAGE}" sh /runner.sh
        elif run_container_scan .appsec-results/gitlab-cs.log "$RUNTIME" run --rm --entrypoint "" \
          -v "$PWD:/workspace" \
          -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
          -w /workspace \
          -e CI_PROJECT_DIR="/workspace" \
          -e CS_SCAN_MODE="archive" \
          -e CS_ARCHIVE="/workspace/.appsec-results/container-image.tar" \
          "${GITLAB_CS_IMAGE}" \
          sh /runner.sh; then
          GITLAB_CS_PID="ran"
        else
          warning "[GitLab CS] Scan failed — check .appsec-results/gitlab-cs.log"
        fi
      else
        warning "[GitLab CS] Failed to pull ${GITLAB_CS_IMAGE}; skipping scan"
        record_skip container_scanning "Could not pull ${GITLAB_CS_IMAGE}, so container scanning did NOT run. Log in to the registry or fix the image path in scanner-preferences.yaml, then re-run this skill."
      fi
      ;;
    error)
      warning "[GitLab CS] Could not prepare a scan target (see container-target.sh output above)."
      ;;
    *)
      info "[GitLab CS] Deferred to CI — no CS_IMAGE and no Dockerfile found."
      record_skip container_scanning "No Dockerfile found and CS_IMAGE is unset, so container scanning did NOT run locally. Write a Dockerfile for this project (or set CS_IMAGE=<image:tag> for an image already in your registry) and re-run this skill to get container coverage."
      info "Container scanning runs post-build in the pipeline."
      ;;
  esac
fi

if [ -z "$EXECUTED_CATEGORIES" ]; then
  if [ -n "$ONLY_CATEGORY" ]; then
    warning "no scanners ran — enabled scanners were skipped (missing image?) or filtered by --only $ONLY_CATEGORY"
  else
    warning "no scanners ran — enabled scanners were skipped (missing image?) or disabled"
  fi
  exit 2
fi

if $DRY_RUN; then
  if dry_python="$(command -v python3 2>/dev/null)" && \
     "$dry_python" -c "import sys" >/dev/null 2>&1; then
    if [ -n "$ONLY_CATEGORY" ]; then
      print_dry_run "$dry_python" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE" --only "$ONLY_CATEGORY"
    else
      print_dry_run "$dry_python" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE"
    fi
  elif [ -z "${PYTHON_INSTALL_URL:-}" ]; then
    warning "python3 is unavailable: install python3 or set settings.python.install_url."
    warning "Would fall back to legacy jq counts with UNKNOWN status; this is NOT an all-clear."
  else
    print_dry_run bash "$SCRIPTS_DIR/resolve-python.sh"
    info "A downloaded python3 would run normalize.py after resolution."
  fi
  [ -z "$SKIPPED_IMAGE_SCANNERS" ] || exit 2
  exit 0
fi

PY_BIN="$(PYTHON_INSTALL_URL="${PYTHON_INSTALL_URL:-}" APPSEC_RESULTS_DIR=".appsec-results" bash "$SCRIPTS_DIR/resolve-python.sh" || true)"
if [ -n "$PY_BIN" ]; then
  if [ -n "$ONLY_CATEGORY" ]; then
    set +e
    "$PY_BIN" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE" --only "$ONLY_CATEGORY"
    gate_rc=$?
    set -e
  else
    set +e
    "$PY_BIN" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE"
    gate_rc=$?
    set -e
  fi
  if [ "$gate_rc" -eq 0 ] && [ -n "$SKIPPED_IMAGE_SCANNERS" ]; then
    warning "enabled scanners skipped for missing images: $SKIPPED_IMAGE_SCANNERS"
    exit 2
  fi
  exit "$gate_rc"
fi

warning "python3 is unavailable: install python3 or set settings.python.install_url."
warning "Falling back to legacy jq counts with UNKNOWN status; this is NOT an all-clear."
JQ_BIN="$(JQ_INSTALL_URL="${JQ_INSTALL_URL:-}" APPSEC_RESULTS_DIR=".appsec-results" bash "$SCRIPTS_DIR/resolve-jq.sh" || true)"
if [ -n "$JQ_BIN" ]; then
  legacy_total=0
  for report in .appsec-results/gl-secret-detection-report.json .appsec-results/gl-container-scanning-report.json; do
    if [ -f "$report" ]; then
      count="$("$JQ_BIN" '[.vulnerabilities[]?] | length' "$report" 2>/dev/null || echo UNKNOWN)"
      info "Legacy count $(basename "$report"): $count"
      case "$count" in *[!0-9]*|'') ;; *) legacy_total=$((legacy_total + count)) ;; esac
    fi
  done
  info "Legacy finding count: $legacy_total (status UNKNOWN)"
else
  warning "jq is also unavailable; legacy finding counts are UNKNOWN."
fi
[ -z "$SKIPPED_IMAGE_SCANNERS" ] || exit 2
exit 0

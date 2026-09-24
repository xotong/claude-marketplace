#!/usr/bin/env bash
# =============================================================================
# remote-match.sh — GitLab-NATIVE dependency scanning via a remote helper project
#
# Local dependency-scanning misses GitLab's server-side SBOM-to-advisory
# matching, which only runs inside a real CI pipeline with a real
# CI_JOB_TOKEN. This script gets that result for a repo scanned on a laptop:
# it uploads ONLY that repo's dependency manifests/lockfiles (never source)
# to a fixed, already-deployed helper GitLab project (see
# reference/remote-matcher/), triggers a real pipeline there on a
# non-default branch (so findings never enter the helper project's own
# Vulnerability Report), and pulls back gl-dependency-scanning-report.json.
#
# One bundle (one generic-package upload, one pipeline) per detected
# language. Bundles are deleted after the report is collected; see
# reference/remote-matcher/README.md for the access model when the caller
# lacks Maintainer.
#
# bash 3.2 (macOS stock /bin/bash) compatible: no associative arrays, no
# mapfile, no ${var,,}. Element expansion ("${arr[@]}") on an empty array
# throws "unbound variable" under `set -u` in 3.2, so it always happens
# behind an "${#arr[@]} -gt 0" guard.
#
# The token (env APPSEC_RESOLVED_TOKEN) is written only into a 0600 curl
# --config temp file, removed on exit; it never appears in argv, stdout,
# stderr, or any other file.
#
# Exit: 0 every requested/detected language ok, or none detected.
#       2 usage error.
#       3 matcher unusable before any pipeline ran anywhere (no token,
#         401/403 on upload, project 404, instance unreachable/TLS) — the
#         caller should fall back to offline matching.
#       4 at least one language failed or timed out, but some pipeline ran.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib-files.sh
. "$SCRIPT_DIR/lib-files.sh"

warning() { printf 'WARNING: %s\n' "$*" >&2; }

usage() {
  cat >&2 <<'USAGE'
Usage: remote-match.sh --project-dir <dir> --results <dir> --instance <url> \
         --matcher-project <id-or-path> [--ds-version <v>] [--ref <ref>] \
         [--language <javascript|python|maven|gradle|go>]... \
         [--timeout <seconds>] [--poll <seconds>]
USAGE
  exit 2
}

PROJECT_DIR=
RESULTS_DIR=
INSTANCE=
MATCHER_PROJECT=
DS_VERSION=1.2.0
REF=scan
TIMEOUT=900
POLL=5
LANGUAGES=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project-dir) [ "$#" -ge 2 ] || usage; PROJECT_DIR=$2; shift 2 ;;
    --results) [ "$#" -ge 2 ] || usage; RESULTS_DIR=$2; shift 2 ;;
    --instance) [ "$#" -ge 2 ] || usage; INSTANCE=$2; shift 2 ;;
    --matcher-project) [ "$#" -ge 2 ] || usage; MATCHER_PROJECT=$2; shift 2 ;;
    --ds-version) [ "$#" -ge 2 ] || usage; DS_VERSION=$2; shift 2 ;;
    --ref) [ "$#" -ge 2 ] || usage; REF=$2; shift 2 ;;
    --language) [ "$#" -ge 2 ] || usage; LANGUAGES+=("$2"); shift 2 ;;
    --timeout) [ "$#" -ge 2 ] || usage; TIMEOUT=$2; shift 2 ;;
    --poll) [ "$#" -ge 2 ] || usage; POLL=$2; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$PROJECT_DIR" ] && [ -n "$RESULTS_DIR" ] && [ -n "$INSTANCE" ] && [ -n "$MATCHER_PROJECT" ] || usage
[ -d "$PROJECT_DIR" ] || { echo "ERROR: no such directory: $PROJECT_DIR" >&2; exit 2; }
case "$TIMEOUT" in ''|*[!0-9]*) usage ;; esac
case "$POLL" in ''|*[!0-9]*) usage ;; esac

# Per-bundle upload cap, bytes (default 25 MiB). A malformed override falls
# back to the default rather than crashing on an env-var typo.
MAX_BUNDLE_BYTES="${APPSEC_REMOTE_MATCH_MAX_BYTES:-26214400}"
case "$MAX_BUNDLE_BYTES" in ''|*[!0-9]*) MAX_BUNDLE_BYTES=26214400 ;; esac

if [ "${#LANGUAGES[@]}" -gt 0 ]; then
  for _l in "${LANGUAGES[@]}"; do
    case "$_l" in
      javascript|python|maven|gradle|go) ;;
      *) echo "ERROR: unknown --language: $_l" >&2; exit 2 ;;
    esac
  done
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
mkdir -p "$RESULTS_DIR"
RESULTS_DIR="$(cd "$RESULTS_DIR" && pwd)"

# ---------------------------------------------------------------------------
# File discovery (manifests/lockfiles only, never source). Exclude list,
# is-excluded predicate and repo-file listing are shared with
# detect-dockerfiles.sh via lib-files.sh.
# ---------------------------------------------------------------------------

basename_of() { printf '%s' "${1##*/}"; }
dirname_of() {
  case "$1" in
    */*) printf '%s' "${1%/*}" ;;
    *) printf '%s' "." ;;
  esac
}

ALL_FILES=()
collect_all_files() {
  local relpath
  while IFS= read -r -d '' relpath; do
    appsec_is_excluded_path "$relpath" && continue
    ALL_FILES+=("$relpath")
  done < <(appsec_list_repo_files "$PROJECT_DIR")
}

# match_by_basename <case-pattern>... : prints every ALL_FILES entry whose
# basename matches any of the given patterns (plain glob patterns, as `case`
# understands them -- a literal name like pom.xml works as-is).
match_by_basename() {
  [ "${#ALL_FILES[@]}" -eq 0 ] && return 0
  local f b pattern
  for f in "${ALL_FILES[@]}"; do
    b=$(basename_of "$f")
    for pattern in "$@"; do
      case "$b" in
        $pattern) printf '%s\n' "$f"; break ;;
      esac
    done
  done
}

match_javascript_lockfiles() {
  match_by_basename package-lock.json npm-shrinkwrap.json yarn.lock pnpm-lock.yaml
}

match_python_files() {
  match_by_basename 'requirements*.txt' Pipfile.lock poetry.lock uv.lock
}

match_maven_pom() { match_by_basename pom.xml; }

match_gradle_files() {
  match_by_basename build.gradle build.gradle.kts settings.gradle settings.gradle.kts
}

match_go_mod() { match_by_basename go.mod; }

detect_present_languages() {
  [ -n "$(match_javascript_lockfiles)" ] && printf '%s\n' javascript
  [ -n "$(match_python_files)" ] && printf '%s\n' python
  [ -n "$(match_maven_pom)" ] && printf '%s\n' maven
  [ -n "$(match_gradle_files)" ] && printf '%s\n' gradle
  [ -n "$(match_go_mod)" ] && printf '%s\n' go
  return 0
}

# sibling_files <matched-file> <sibling-name>...: prints each <sibling-name>
# that exists next to <matched-file> (same directory), repo-relative.
sibling_files() {
  local f=$1 dir sib
  shift
  dir=$(dirname_of "$f")
  for sib in "$@"; do
    if [ "$dir" = "." ]; then
      [ -f "$PROJECT_DIR/$sib" ] && printf '%s\n' "$sib"
    else
      [ -f "$PROJECT_DIR/$dir/$sib" ] && printf '%s\n' "$dir/$sib"
    fi
  done
}

# Repo-relative paths to include in one language's bundle. Never source: only
# the manifest/lockfile matches above plus their documented siblings.
bundle_files_for() {
  local lang=$1 f
  case "$lang" in
    javascript)
      match_javascript_lockfiles | while IFS= read -r f; do
        printf '%s\n' "$f"
        sibling_files "$f" package.json
      done
      ;;
    python)
      match_python_files | while IFS= read -r f; do
        printf '%s\n' "$f"
        sibling_files "$f" pyproject.toml Pipfile setup.cfg setup.py
      done
      ;;
    maven)
      match_maven_pom
      if [ "${#ALL_FILES[@]}" -gt 0 ]; then
        for f in "${ALL_FILES[@]}"; do
          case "$f" in
            .mvn/*|*/.mvn/*) printf '%s\n' "$f" ;;
          esac
        done
      fi
      ;;
    gradle)
      match_gradle_files
      if [ "${#ALL_FILES[@]}" -gt 0 ]; then
        for f in "${ALL_FILES[@]}"; do
          case "$(basename_of "$f")" in
            gradle.properties|gradle.lockfile) printf '%s\n' "$f" ;;
            # A gradle lockfile plugin's own *.lockfile output lives under
            # gradle/dependency-locks/ -- a bare *.lockfile match elsewhere
            # (any language's lockfile format that happens to share the
            # suffix) is not ours to upload.
            *.lockfile)
              case "$f" in
                gradle/dependency-locks/*|*/gradle/dependency-locks/*) printf '%s\n' "$f" ;;
              esac
              ;;
          esac
          case "$f" in
            gradle/libs.versions.toml|*/gradle/libs.versions.toml) printf '%s\n' "$f" ;;
            gradle/wrapper/gradle-wrapper.properties|*/gradle/wrapper/gradle-wrapper.properties) printf '%s\n' "$f" ;;
          esac
        done
      fi
      ;;
    go)
      match_go_mod | while IFS= read -r f; do
        printf '%s\n' "$f"
        sibling_files "$f" go.sum
      done
      ;;
  esac
  return 0
}

# ---------------------------------------------------------------------------
# HTTP (token only ever in the curl --config file, never argv)
# ---------------------------------------------------------------------------
HTTP_TIMEOUT=60
CURL_CONFIG=""
# See cleanup_on_exit (installed at the top of Main, once cleanup_bundle and
# cancel_pipeline below are defined) for the trap that removes this file.

LAST_HTTP_CODE=000

api_base() { printf '%s/api/v4' "${INSTANCE%/}"; }

# http_request <method> <url> <outfile> [extra curl args...]
# Single choke point for every GitLab API call this script makes: writes the
# response body to outfile, sets LAST_HTTP_CODE, and applies --config
# <CURL_CONFIG> (the 0600 token file) whenever one exists. Anything
# method-specific (--upload-file, a JSON body, --retry, a longer --max-time
# for the upload) is the caller's [extra curl args...] -- appended after the
# default --max-time, so a caller's own --max-time still wins (curl takes the
# last occurrence of a repeated flag).
http_request() {
  local method=$1 url=$2 outfile=$3 code
  shift 3
  if [ -n "$CURL_CONFIG" ]; then
    code=$(curl -sS -o "$outfile" -w '%{http_code}' --max-time "$HTTP_TIMEOUT" --config "$CURL_CONFIG" -X "$method" "$@" "$url" 2>/dev/null) || true
  else
    code=$(curl -sS -o "$outfile" -w '%{http_code}' --max-time "$HTTP_TIMEOUT" -X "$method" "$@" "$url" 2>/dev/null) || true
  fi
  LAST_HTTP_CODE=${code:-000}
}

encode_project() {
  case "$1" in
    ''|*[!0-9]*) printf '%s' "$1" | sed 's#/#%2F#g' ;;
    *) printf '%s' "$1" ;;
  esac
}

random_hex6() { od -An -N3 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n'; }

# ---------------------------------------------------------------------------
# JSON (jq if present, else python3; see resolve-jq.sh / resolve-python.sh)
# ---------------------------------------------------------------------------
JQ_BIN=""
PY_BIN=""

json_field() { # file key -> scalar or ""
  local file=$1 key=$2
  if [ -n "$JQ_BIN" ]; then
    "$JQ_BIN" -r --arg k "$key" '.[$k] // empty' "$file" 2>/dev/null
  else
    "$PY_BIN" - "$file" "$key" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
v = d.get(sys.argv[2]) if isinstance(d, dict) else None
print("" if v is None else v)
PY
  fi
}

job_field_by_name() { # file job-name field -> scalar or ""
  local file=$1 name=$2 field=$3
  if [ -n "$JQ_BIN" ]; then
    "$JQ_BIN" -r --arg n "$name" --arg f "$field" \
      '([.[] | select(.name == $n)] | .[0][$f]) // empty' "$file" 2>/dev/null
  else
    "$PY_BIN" - "$file" "$name" "$field" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = []
name, field = sys.argv[2], sys.argv[3]
for item in d if isinstance(d, list) else []:
    if isinstance(item, dict) and item.get("name") == name:
        v = item.get(field)
        print("" if v is None else v)
        break
PY
  fi
}

count_findings() { # file -> int
  local file=$1 n
  if [ -n "$JQ_BIN" ]; then
    n=$("$JQ_BIN" '(.vulnerabilities // []) | length' "$file" 2>/dev/null) || n=0
  else
    n=$("$PY_BIN" - "$file" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
print(len((d.get("vulnerabilities") or []) if isinstance(d, dict) else []))
PY
) || n=0
  fi
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  printf '%s' "$n"
}

first_package_id() { # file -> id or ""
  local file=$1
  if [ -n "$JQ_BIN" ]; then
    "$JQ_BIN" -r '(.[0].id) // empty' "$file" 2>/dev/null
  else
    "$PY_BIN" - "$file" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = []
print(d[0]["id"] if isinstance(d, list) and d else "")
PY
  fi
}

build_trigger_payload() { # ref lang bundle dsver -> json on stdout
  local ref=$1 lang=$2 bundle=$3 dsver=$4
  if [ -n "$JQ_BIN" ]; then
    "$JQ_BIN" -n --arg ref "$ref" --arg lang "$lang" --arg bundle "$bundle" --arg dsver "$dsver" \
      '{ref:$ref, inputs:{language:$lang, bundle:$bundle, ds_version:$dsver}}'
  else
    "$PY_BIN" - "$ref" "$lang" "$bundle" "$dsver" <<'PY'
import json, sys
ref, lang, bundle, dsver = sys.argv[1:5]
print(json.dumps({"ref": ref, "inputs": {"language": lang, "bundle": bundle, "ds_version": dsver}}))
PY
  fi
}

write_result() { # lang status pid purl jstatus findings reason bid dur outfile
  local lang=$1 status=$2 pid=$3 purl=$4 jstatus=$5 findings=$6 reason=$7 bid=$8 dur=$9 outfile=${10}
  if [ -n "$JQ_BIN" ]; then
    "$JQ_BIN" -n \
      --arg language "$lang" --arg status "$status" --arg pipeline_id "$pid" \
      --arg pipeline_url "$purl" --arg job_status "$jstatus" --arg reason "$reason" \
      --arg bundle_id "$bid" --argjson findings "${findings:-0}" --argjson duration_s "${dur:-0}" \
      '{language:$language, status:$status, pipeline_id:$pipeline_id, pipeline_url:$pipeline_url,
        job_status:$job_status, findings:$findings, reason:$reason, bundle_id:$bundle_id,
        duration_s:$duration_s}' >"$outfile"
  else
    "$PY_BIN" - "$outfile" "$lang" "$status" "$pid" "$purl" "$jstatus" "$findings" "$reason" "$bid" "$dur" <<'PY'
import json, sys
outfile, lang, status, pid, purl, jstatus, findings, reason, bid, dur = sys.argv[1:11]
data = {
    "language": lang, "status": status, "pipeline_id": pid, "pipeline_url": purl,
    "job_status": jstatus, "findings": int(findings or 0), "reason": reason,
    "bundle_id": bid, "duration_s": int(dur or 0),
}
with open(outfile, "w") as fh:
    json.dump(data, fh)
PY
  fi
}

trace_reason() { # file -> one-line summary
  local file=$1
  [ -f "$file" ] || { printf '%s' ""; return 0; }
  tail -n 80 "$file" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -n 3 | tr '\n' ' ' \
    | sed -e 's/  */ /g' -e 's/^ *//' -e 's/ *$//' | cut -c1-400
}

emit_line() { printf 'REMOTE-MATCH: language=%s status=%s findings=%s pipeline=%s\n' "$1" "$2" "${3:-0}" "${4:-}"; }

# ---------------------------------------------------------------------------
# Aggregate outcome (drives the exit code)
# ---------------------------------------------------------------------------
ANY_PIPELINE_TRIGGERED=false
HAD_UNUSABLE_FAILURE=false
HAD_ANY_FAILURE=false

# Per-language state, indexed by position in LANGS (phase 1 triggers every
# language's pipeline sequentially; phase 2 then polls all of them together).
# INFLIGHT_BUNDLE_ID / INFLIGHT_PIPELINE_ID are read by cleanup_on_exit so a
# Ctrl-C/SIGTERM mid-poll still deletes every uploaded bundle and cancels
# every still-running pipeline, not just one -- each entry is cleared as soon
# as that language's bundle/pipeline is no longer this run's to clean up (and
# a non-empty INFLIGHT_PIPELINE_ID[i] doubles as "still pending" in phase 2).
# BUNDLE_ID/PIPELINE_ID/PIPELINE_URL/T0 persist for the whole run since
# finalize_language needs them after INFLIGHT_* is cleared.
LANGS=()
BUNDLE_ID=()
PIPELINE_ID=()
PIPELINE_URL=()
T0=()
INFLIGHT_BUNDLE_ID=()
INFLIGHT_PIPELINE_ID=()
ENC_PROJECT=""

finish_language() { # lang status pid purl jstatus findings reason bid t0 unusable
  local lang=$1 status=$2 pid=$3 purl=$4 jstatus=$5 findings=$6 reason=$7 bid=$8 t0=$9 unusable=${10}
  local t1 dur out_dir
  t1=$(date +%s); dur=$((t1 - t0))
  out_dir="$RESULTS_DIR/remote-ds/$lang"
  write_result "$lang" "$status" "$pid" "$purl" "$jstatus" "$findings" "$reason" "$bid" "$dur" "$out_dir/result.json"
  if [ "$status" != ok ]; then
    HAD_ANY_FAILURE=true
    [ "$unusable" = true ] && HAD_UNUSABLE_FAILURE=true
  fi
  return 0
}

# emit_results: prints the REMOTE-MATCH / REMOTE-MATCH-REASON stdout lines
# for every language in LANGS order, once phase 1 + phase 2 are both done for
# all of them -- so the order stays stable regardless of which pipeline
# actually finished first. Reads back each language's own result.json (the
# source of truth finish_language just wrote) rather than stashing a second
# copy of the same fields in more arrays.
emit_results() {
  local idx lang rf status findings purl reason
  idx=0
  while [ "$idx" -lt "${#LANGS[@]}" ]; do
    lang=${LANGS[$idx]}
    rf="$RESULTS_DIR/remote-ds/$lang/result.json"
    status=$(json_field "$rf" status)
    findings=$(json_field "$rf" findings)
    purl=$(json_field "$rf" pipeline_url)
    emit_line "$lang" "$status" "$findings" "$purl"
    if [ "$status" != ok ]; then
      reason=$(json_field "$rf" reason)
      printf 'REMOTE-MATCH-REASON: language=%s %s\n' "$lang" "$reason"
    fi
    idx=$((idx + 1))
  done
}

cleanup_bundle() { # idx bundle_id enc_project
  local idx=$1 bid=$2 enc=$3 list_body pkg_id del_body
  # Cleanup is attempted exactly once per bundle, right here, regardless of
  # outcome -- so it is no longer "in flight" as of this call, not only once
  # the DELETE below succeeds.
  INFLIGHT_BUNDLE_ID[idx]=""
  list_body=$(mktemp) || return 0
  http_request GET "$(api_base)/projects/$enc/packages?package_name=appsec-bundles&package_version=$bid" "$list_body" --retry 2
  if [ "$LAST_HTTP_CODE" != 200 ]; then
    warning "could not list packages to clean up bundle $bid (HTTP $LAST_HTTP_CODE)"
    rm -f "$list_body"
    return 0
  fi
  pkg_id=$(first_package_id "$list_body")
  rm -f "$list_body"
  [ -n "$pkg_id" ] || { warning "no package found for bundle $bid; nothing to delete"; return 0; }
  del_body=$(mktemp) || return 0
  http_request DELETE "$(api_base)/projects/$enc/packages/$pkg_id" "$del_body"
  rm -f "$del_body"
  case "$LAST_HTTP_CODE" in
    200|202|204) : ;;
    403) printf 'ADVISORY: could not delete bundle %s (needs Maintainer); the platform team'"'"'s cleanup will remove it\n' "$bid" ;;
    *) warning "could not delete bundle $bid (HTTP $LAST_HTTP_CODE)" ;;
  esac
  return 0
}

# cancel_pipeline <pid> <enc_project>: best-effort POST .../cancel. Only ever
# called from cleanup_on_exit (an abandoned-mid-poll pipeline), so a failure
# here is swallowed -- there is no run left to fail.
cancel_pipeline() {
  local pid=$1 enc=$2 out
  [ -n "$pid" ] || return 0
  out=$(mktemp) || return 0
  http_request POST "$(api_base)/projects/$enc/pipelines/$pid/cancel" "$out" 2>/dev/null || true
  rm -f "$out"
  return 0
}

# Runs on every exit (normal, `exit N`, or a caught INT/TERM -- see the traps
# installed at the top of Main). Best-effort: an interrupted run must not
# leave an uploaded bundle or a running pipeline behind just because the
# script stopped watching them.
cleanup_on_exit() {
  local idx=0
  while [ "$idx" -lt "${#LANGS[@]}" ]; do
    [ -n "${INFLIGHT_PIPELINE_ID[idx]:-}" ] && cancel_pipeline "${INFLIGHT_PIPELINE_ID[idx]}" "$ENC_PROJECT"
    [ -n "${INFLIGHT_BUNDLE_ID[idx]:-}" ] && cleanup_bundle "$idx" "${INFLIGHT_BUNDLE_ID[idx]}" "$ENC_PROJECT"
    idx=$((idx + 1))
  done
  [ -n "$CURL_CONFIG" ] && rm -f "$CURL_CONFIG"
  return 0
}

# poll_all_pending: polls every pipeline phase 1 triggered together, one GET
# per still-pending pipeline per --poll interval, with one --timeout shared
# by all of them and measured from here. As each pipeline goes terminal (or
# the shared timeout is hit) it is handed to finalize_language immediately --
# stdout stays in LANGS order regardless (see emit_results). Called directly
# (never as `x=$(poll_all_pending)`): a command substitution forks a
# subshell, and bash defers a pending trap until that whole subshell's
# command finishes -- which, for a loop that can run up to --timeout seconds,
# would make Ctrl-C/SIGTERM sit unresponsive for the same --timeout instead
# of the ~$POLL seconds a direct call gives it.
poll_all_pending() {
  local start now idx pid status body lang still_pending
  start=$(date +%s)
  while :; do
    idx=0
    while [ "$idx" -lt "${#LANGS[@]}" ]; do
      pid=${INFLIGHT_PIPELINE_ID[idx]:-}
      if [ -n "$pid" ]; then
        body=$(mktemp) || { idx=$((idx + 1)); continue; }
        http_request GET "$(api_base)/projects/$ENC_PROJECT/pipelines/$pid" "$body" --retry 2
        if [ "$LAST_HTTP_CODE" = 200 ]; then
          status=$(json_field "$body" status)
          case "$status" in
            created|waiting_for_resource|preparing|pending|running) ;;
            *)
              rm -f "$body"
              INFLIGHT_PIPELINE_ID[idx]=""
              lang=${LANGS[$idx]}
              finalize_language "$idx" "$lang" "$status"
              idx=$((idx + 1))
              continue
              ;;
          esac
        fi
        rm -f "$body"
      fi
      idx=$((idx + 1))
    done

    still_pending=false
    idx=0
    while [ "$idx" -lt "${#LANGS[@]}" ]; do
      [ -n "${INFLIGHT_PIPELINE_ID[idx]:-}" ] && still_pending=true
      idx=$((idx + 1))
    done
    [ "$still_pending" = false ] && return 0

    now=$(date +%s)
    if [ $((now - start)) -ge "$TIMEOUT" ]; then
      idx=0
      while [ "$idx" -lt "${#LANGS[@]}" ]; do
        pid=${INFLIGHT_PIPELINE_ID[idx]:-}
        if [ -n "$pid" ]; then
          INFLIGHT_PIPELINE_ID[idx]=""
          lang=${LANGS[$idx]}
          finalize_language "$idx" "$lang" "__timeout__"
        fi
        idx=$((idx + 1))
      done
      return 0
    fi
    sleep "$POLL"
  done
}

trigger_language() { # idx lang -- phase 1: build + size-check + upload + trigger
  local idx=$1 lang=$2
  local out_dir="$RESULTS_DIR/remote-ds/$lang"
  local tmp_dir="$out_dir/.tmp"
  mkdir -p "$out_dir" "$tmp_dir"
  local t0; t0=$(date +%s)
  T0[idx]=$t0

  local files nfiles
  files=$(bundle_files_for "$lang" | LC_ALL=C sort -u)
  printf '%s\n' "$files" | sed '/^$/d' >"$out_dir/bundle-manifest.txt"
  nfiles=$(sed '/^$/d' "$out_dir/bundle-manifest.txt" | wc -l | tr -d ' ')

  if [ "$nfiles" -eq 0 ]; then
    finish_language "$lang" error "" "" "" 0 \
      "no $lang manifest/lockfiles found under $PROJECT_DIR" "" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  if [ -z "$RESOLVED_TOKEN" ]; then
    finish_language "$lang" error "" "" "" 0 \
      "APPSEC_RESOLVED_TOKEN is not set; cannot authenticate to $INSTANCE" "" "$t0" true
    rm -rf "$tmp_dir"
    return 0
  fi

  if [ -z "$JQ_BIN" ] && [ -z "$PY_BIN" ]; then
    finish_language "$lang" error "" "" "" 0 \
      "neither jq nor python3 available to parse matcher API responses" "" "$t0" true
    rm -rf "$tmp_dir"
    return 0
  fi

  local bundle_id
  bundle_id="${lang}-$(date -u +%Y%m%d%H%M%S)-$(random_hex6)"

  local tarball="$tmp_dir/bundle.tar.gz"
  if ! tar -czf "$tarball" -C "$PROJECT_DIR" -T "$out_dir/bundle-manifest.txt" 2>"$tmp_dir/tar-err"; then
    finish_language "$lang" error "" "" "" 0 \
      "failed to build bundle archive: $(tail -n1 "$tmp_dir/tar-err" 2>/dev/null)" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  local bundle_bytes
  bundle_bytes=$(wc -c <"$tarball" | tr -d ' ')
  if [ "$bundle_bytes" -gt "$MAX_BUNDLE_BYTES" ]; then
    finish_language "$lang" error "" "" "" 0 \
      "bundle archive is ${bundle_bytes} bytes, over the ${MAX_BUNDLE_BYTES}-byte cap (APPSEC_REMOTE_MATCH_MAX_BYTES) — nothing uploaded" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  local put_url upload_body
  put_url="$(api_base)/projects/$ENC_PROJECT/packages/generic/appsec-bundles/$bundle_id/bundle.tar.gz"
  upload_body="$tmp_dir/upload-response"
  http_request PUT "$put_url" "$upload_body" --max-time 120 --upload-file "$tarball"
  case "$LAST_HTTP_CODE" in
    200|201) : ;;
    401|403)
      finish_language "$lang" error "" "" "" 0 \
        "bundle upload rejected (HTTP $LAST_HTTP_CODE) — token lacks access to matcher project" "$bundle_id" "$t0" true
      rm -rf "$tmp_dir"
      return 0
      ;;
    404)
      finish_language "$lang" error "" "" "" 0 \
        "matcher project not found (HTTP 404 on upload) — check --matcher-project/--instance" "$bundle_id" "$t0" true
      rm -rf "$tmp_dir"
      return 0
      ;;
    000)
      finish_language "$lang" error "" "" "" 0 \
        "could not reach $INSTANCE (connection or TLS error)" "$bundle_id" "$t0" true
      rm -rf "$tmp_dir"
      return 0
      ;;
    *)
      finish_language "$lang" error "" "" "" 0 \
        "bundle upload failed (HTTP $LAST_HTTP_CODE)" "$bundle_id" "$t0" false
      rm -rf "$tmp_dir"
      return 0
      ;;
  esac

  # Uploaded and now sitting in the matcher project -- an interrupt from here
  # on must delete it, not just stop watching it.
  BUNDLE_ID[idx]="$bundle_id"
  INFLIGHT_BUNDLE_ID[idx]="$bundle_id"

  local payload_file="$tmp_dir/trigger-payload.json"
  local trig_body="$tmp_dir/trigger-response.json"
  build_trigger_payload "$REF" "$lang" "$bundle_id" "$DS_VERSION" >"$payload_file"
  http_request POST "$(api_base)/projects/$ENC_PROJECT/pipeline" "$trig_body" \
    -H "Content-Type: application/json" --data-binary "@$payload_file"
  if [ "$LAST_HTTP_CODE" != 201 ]; then
    cleanup_bundle "$idx" "$bundle_id" "$ENC_PROJECT"
    finish_language "$lang" error "" "" "" 0 \
      "pipeline trigger failed (HTTP $LAST_HTTP_CODE)" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  ANY_PIPELINE_TRIGGERED=true
  local pipeline_id pipeline_url
  pipeline_id=$(json_field "$trig_body" id)
  pipeline_url=$(json_field "$trig_body" web_url)
  PIPELINE_ID[idx]="$pipeline_id"
  PIPELINE_URL[idx]="$pipeline_url"
  # Triggered and now running on the matcher project -- phase 2 (poll_all_pending)
  # picks this up via a non-empty INFLIGHT_PIPELINE_ID[idx].
  INFLIGHT_PIPELINE_ID[idx]="$pipeline_id"
  return 0
}

finalize_language() { # idx lang pipeline_final_status ("__timeout__" = never went terminal)
  local idx=$1 lang=$2 final_status=$3
  local out_dir="$RESULTS_DIR/remote-ds/$lang"
  local tmp_dir="$out_dir/.tmp"
  local bundle_id=${BUNDLE_ID[$idx]}
  local pipeline_id=${PIPELINE_ID[$idx]}
  local pipeline_url=${PIPELINE_URL[$idx]}
  local t0=${T0[$idx]}

  if [ "$final_status" = "__timeout__" ]; then
    cleanup_bundle "$idx" "$bundle_id" "$ENC_PROJECT"
    finish_language "$lang" timeout "$pipeline_id" "$pipeline_url" "" 0 \
      "pipeline $pipeline_id did not reach a terminal state within ${TIMEOUT}s" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  local jobs_body="$tmp_dir/jobs.json"
  http_request GET "$(api_base)/projects/$ENC_PROJECT/pipelines/$pipeline_id/jobs" "$jobs_body" --retry 2
  if [ "$LAST_HTTP_CODE" != 200 ]; then
    cleanup_bundle "$idx" "$bundle_id" "$ENC_PROJECT"
    finish_language "$lang" error "$pipeline_id" "$pipeline_url" "" 0 \
      "could not list jobs for pipeline $pipeline_id (HTTP $LAST_HTTP_CODE)" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  local job_id job_status
  job_id=$(job_field_by_name "$jobs_body" "dependency-scanning" id)
  job_status=$(job_field_by_name "$jobs_body" "dependency-scanning" status)

  if [ -z "$job_id" ]; then
    cleanup_bundle "$idx" "$bundle_id" "$ENC_PROJECT"
    finish_language "$lang" error "$pipeline_id" "$pipeline_url" "" 0 \
      "pipeline $pipeline_id has no job named dependency-scanning (pipeline status: $final_status)" "$bundle_id" "$t0" false
    rm -rf "$tmp_dir"
    return 0
  fi

  local status findings reason
  case "$job_status" in
    success)
      local report_body="$out_dir/gl-dependency-scanning-report.json"
      http_request GET "$(api_base)/projects/$ENC_PROJECT/jobs/$job_id/artifacts/gl-dependency-scanning-report.json" "$report_body" --retry 2
      if [ "$LAST_HTTP_CODE" = 200 ]; then
        status=ok
        findings=$(count_findings "$report_body")
        reason=""
      else
        status=error
        findings=0
        rm -f "$report_body"
        reason="dependency-scanning job succeeded but artifact download failed (HTTP $LAST_HTTP_CODE)"
      fi
      ;;
    skipped)
      status=failed
      findings=0
      local fb_id
      fb_id=$(job_field_by_name "$jobs_body" "fetch-bundle" id)
      if [ -n "$fb_id" ]; then
        http_request GET "$(api_base)/projects/$ENC_PROJECT/jobs/$fb_id/trace" "$tmp_dir/trace.txt" --retry 2
        reason="fetch-bundle failed, dependency-scanning skipped: $(trace_reason "$tmp_dir/trace.txt")"
      else
        reason="dependency-scanning job skipped (upstream job failed)"
      fi
      ;;
    *)
      status=failed
      findings=0
      http_request GET "$(api_base)/projects/$ENC_PROJECT/jobs/$job_id/trace" "$tmp_dir/trace.txt" --retry 2
      reason="dependency-scanning job $job_status: $(trace_reason "$tmp_dir/trace.txt")"
      ;;
  esac

  cleanup_bundle "$idx" "$bundle_id" "$ENC_PROJECT"
  finish_language "$lang" "$status" "$pipeline_id" "$pipeline_url" "$job_status" "$findings" "$reason" "$bundle_id" "$t0" false
  rm -rf "$tmp_dir"
  return 0
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# ENC_PROJECT now (cheap, no I/O) so cleanup_on_exit has it from here on --
# before anything that could actually create a bundle or pipeline to clean up.
ENC_PROJECT=$(encode_project "$MATCHER_PROJECT")
trap cleanup_on_exit EXIT
# A caught INT/TERM `exit`s explicitly (128+signal, the conventional code) so
# the EXIT trap above runs cleanup_on_exit -- bash does not otherwise treat a
# trapped signal as a reason to stop the script.
trap 'exit 130' INT
trap 'exit 143' TERM

collect_all_files

if [ "${#LANGUAGES[@]}" -gt 0 ]; then
  LANGS=("${LANGUAGES[@]}")
else
  while IFS= read -r _dl; do LANGS+=("$_dl"); done < <(detect_present_languages)
fi

if [ "${#LANGS[@]}" -eq 0 ]; then
  echo "REMOTE-MATCH: none detected"
  exit 0
fi

RESOLVED_TOKEN=$(printenv APPSEC_RESOLVED_TOKEN 2>/dev/null || true)
JQ_BIN="$(JQ_INSTALL_URL="${JQ_INSTALL_URL:-}" APPSEC_RESULTS_DIR="$RESULTS_DIR" bash "$SCRIPT_DIR/resolve-jq.sh" 2>/dev/null || true)"
PY_BIN="$(PYTHON_INSTALL_URL="${PYTHON_INSTALL_URL:-}" APPSEC_RESULTS_DIR="$RESULTS_DIR" bash "$SCRIPT_DIR/resolve-python.sh" 2>/dev/null || true)"

if [ -n "$RESOLVED_TOKEN" ]; then
  CURL_CONFIG=$(mktemp) || CURL_CONFIG=""
  if [ -n "$CURL_CONFIG" ]; then
    chmod 600 "$CURL_CONFIG"
    printf 'header = "Authorization: Bearer %s"\n' "$RESOLVED_TOKEN" >"$CURL_CONFIG"
  fi
fi

# Phase 1: build + size-check + upload + trigger every language sequentially
# (fast, no polling) so every pipeline is already running on the matcher
# project concurrently before phase 2 starts watching any of them.
_idx=0
while [ "$_idx" -lt "${#LANGS[@]}" ]; do
  trigger_language "$_idx" "${LANGS[$_idx]}"
  _idx=$((_idx + 1))
done

# Phase 2: poll every still-running pipeline together, one shared timeout.
poll_all_pending

# REMOTE-MATCH / REMOTE-MATCH-REASON stdout, in LANGS order, now that every
# language is done.
emit_results

if [ "$HAD_ANY_FAILURE" = true ]; then
  if [ "$ANY_PIPELINE_TRIGGERED" = false ] && [ "$HAD_UNUSABLE_FAILURE" = true ]; then
    exit 3
  fi
  exit 4
fi
exit 0

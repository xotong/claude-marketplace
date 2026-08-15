#!/usr/bin/env bash
set -euo pipefail

ONLY_CATEGORY=
DRY_RUN=false
RAN_CATEGORIES=
EXECUTED_CATEGORIES=
DS_RAN=false
DS_FAILED=false
SKIPPED_IMAGE_SCANNERS=
CONFIG_ERRORS=

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

# shellcheck source=scripts/classify-error.sh
. "$SCRIPTS_DIR/classify-error.sh"

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

# record_config_error [category] <actionable reason>
#
# A configuration error is terminal for whatever it blocks: no retry, no other
# image, no other endpoint will authenticate a credential the admin has not set,
# and trying anyway just buries the cause under a scan that reads like a result.
#
# It rides record_skip so the coverage record needs no new shape -- the category
# still lands in missing_report with coverage_complete false, still synthesises
# its HIGH APPSEC-REPORT-* finding, and normalize.py carries this text verbatim
# into evidence.why. What it adds is a non-zero exit that a passing gate (or
# `fail_on: none`, which always exits 0) would otherwise swallow.
#
# The category is optional: a refused package registry is a run-level problem,
# not a scanner that failed to produce a report.
record_config_error() {
  cfg_category=$1
  cfg_reason=$2
  printf 'CONFIG-ERROR: %s\n' "$cfg_reason" >&2
  [ -z "$cfg_category" ] || record_skip "$cfg_category" "CONFIG-ERROR: $cfg_reason"
  if [ -n "$CONFIG_ERRORS" ]; then
    CONFIG_ERRORS="$CONFIG_ERRORS
$cfg_reason"
  else
    CONFIG_ERRORS=$cfg_reason
  fi
}

# pull_image <category> <label> <image> <consequence>
#
# Returns 0 on success; on failure records the skip itself and returns 1. Splits
# the two causes that used to share one message and one outcome: a registry that
# REFUSED us is a config error, while one we could not reach keeps the existing
# advice and the existing graceful skip.
pull_image() {
  pull_category=$1
  pull_label=$2
  pull_ref=$3
  pull_consequence=$4
  pull_log=".appsec-results/pull-${pull_category}.log"
  if run_cmd "$RUNTIME" pull "$pull_ref" 2>"$pull_log"; then
    rm -f "$pull_log"
    return 0
  fi
  if is_auth_error "$(cat "$pull_log" 2>/dev/null)"; then
    record_config_error "$pull_category" "The registry refused our credentials for ${pull_ref}, so ${pull_consequence} Run '$RUNTIME login <registry-host>', or set the credentials named by settings.container_registry in scanner-preferences.yaml (${CS_USER_ENV:-CS_REGISTRY_USER} / ${CS_PASS_ENV:-CS_REGISTRY_PASSWORD}). Details: $pull_log"
    return 1
  fi
  warning "[$pull_label] Failed to pull ${pull_ref}; skipping scan"
  record_skip "$pull_category" "Could not pull ${pull_ref}, so ${pull_consequence} Log in to the registry or fix the image path in scanner-preferences.yaml, then re-run this skill. Details: $pull_log"
  return 1
}

# Printed after the normalizer's summary, so it is the last thing on screen, and
# it exits 2 whatever the gate said. `fail_on: none` always exits 0 on findings —
# without this override the whole "stop and report" contract would come down to a
# warning somewhere up the scrollback.
report_config_errors() {
  [ -n "$CONFIG_ERRORS" ] || return 0
  printf '\n' >&2
  error "CONFIGURATION ERRORS — this run is NOT a valid scan"
  printf '%s\n' "$CONFIG_ERRORS" | while IFS= read -r cfg_line; do
    [ -n "$cfg_line" ] || continue
    printf '  - %s\n' "$cfg_line" >&2
  done
  error "No workaround was attempted: only your admin config can fix these. Fix them and re-run this skill."
  exit 2
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
# Credential variable NAMES, not values. The component reads $ARTIFACTORY_USER /
# $ARTIFACTORY_PASSWORD, but an estate that already names them something else
# should not have to rename its CI variables to run this locally.
ARTIFACTORY_USER_ENV="${ARTIFACTORY_USER_ENV:-ARTIFACTORY_USER}"
ARTIFACTORY_PASSWORD_ENV="${ARTIFACTORY_PASSWORD_ENV:-ARTIFACTORY_PASSWORD}"
CS_USER_ENV="${CS_USER_ENV:-CS_REGISTRY_USER}"
CS_PASS_ENV="${CS_PASS_ENV:-CS_REGISTRY_PASSWORD}"

# --- airgap plumbing (settings.ca_bundle / maven_settings / pip_index_url) ----
# These are HOST paths and a HOST url. Passing a host path straight into a
# container points the tool at a file that is not there, and the failure reads
# like a broken mirror or a network outage rather than a missing mount — the
# expensive kind of misdiagnosis. So each one is mounted first, and the value
# handed to the scanner is the IN-CONTAINER path.
# Empty config value (the shipped default) = nothing mounted, nothing exported.
host_path() {
  # docker/podman -v refuses a relative source; config paths may be relative.
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$PWD" "$1" ;;
  esac
}

CA_ARGS=()
if [ -n "${CA_BUNDLE:-}" ]; then
  ca_host_path=$(host_path "$CA_BUNDLE")
  if [ -r "$ca_host_path" ]; then
    CA_ARGS=(-v "$ca_host_path:/appsec/ca-bundle.pem:ro"
             -e ADDITIONAL_CA_CERT_BUNDLE=/appsec/ca-bundle.pem)
  else
    warning "settings.ca_bundle points at $CA_BUNDLE, which is not readable here;"
    warning "  scanners will run without it and TLS to internal hosts may fail."
  fi
fi

# MAVEN_SETTINGS keeps its legacy meaning (a path the container can already see)
# whenever the value does not name a readable file on this host.
MAVEN_MOUNT_ARGS=()
MAVEN_SETTINGS_PATH="${MAVEN_SETTINGS:-}"
if [ -n "$MAVEN_SETTINGS_PATH" ]; then
  maven_host_path=$(host_path "$MAVEN_SETTINGS_PATH")
  if [ -r "$maven_host_path" ]; then
    MAVEN_MOUNT_ARGS=(-v "$maven_host_path:/appsec/maven-settings.xml:ro")
    MAVEN_SETTINGS_PATH=/appsec/maven-settings.xml
  fi
fi

# Dependency-resolution inputs the analyzer reads from the environment. The
# component's own defaults (pypi.org, ./settings.xml) only work with public
# internet, so an airgapped run hangs on PyPI and reports a broken SBOM.
DS_AIRGAP_ARGS=()
if [ -n "${APPSEC_PIP_INDEX_URL:-}" ]; then
  DS_AIRGAP_ARGS=(-e PIP_INDEX_URL="$APPSEC_PIP_INDEX_URL")
fi
if [ -n "$MAVEN_SETTINGS_PATH" ]; then
  # Same shape the component exports: MAVEN_ARGS="-s <settings path>".
  DS_AIRGAP_ARGS+=(-e MAVEN_ARGS="-s $MAVEN_SETTINGS_PATH")
fi

# Workspace-relative path of the Dockerfile, for CS_DOCKERFILE_PATH.
# ponytail: this repeats container-target.sh's discovery order because that
# script only prints "mode|value"; when it may be edited, have it report the
# Dockerfile it found and delete this.
find_dockerfile() {
  if [ -n "${DOCKERFILE:-}" ] && [ -f "${DOCKERFILE}" ]; then
    printf '%s' "${DOCKERFILE}"
  elif [ -f ./Dockerfile ]; then
    printf 'Dockerfile'
  else
    find . -maxdepth 3 \
      -type d \( -name '.git' -o -name 'node_modules' \) -prune -o \
      -type f \( -name 'Dockerfile' -o -name '*.Dockerfile' \) -print 2>/dev/null |
      while IFS= read -r match; do
        printf '%s' "$match"
        break
      done
  fi
}

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

# A filesystem-safe name for one SAST unit. "." is the repo root.
unit_slug() {
  case "$1" in
    .|"") printf 'root' ;;
    *) printf '%s' "$1" | sed 's#[^A-Za-z0-9._-]#-#g' ;;
  esac
}

# One report per unit — but only when there IS more than one. A single-unit
# repository keeps writing plain fortify-sast.fpr, so nothing downstream (or in
# anyone's tooling) sees a new filename for a scan whose shape did not change.
unit_fpr() {
  if [ "${SAST_UNIT_COUNT:-1}" -le 1 ]; then
    printf 'fortify-sast.fpr'
  else
    printf 'fortify-sast-%s.fpr' "$(unit_slug "$1")"
  fi
}

# clear_stale_reports <category>: delete the PREVIOUS run's reports for a
# category this run is going to attempt (see the single caller below).
#
# Every scanner runner already rm's its own outputs — but from INSIDE the
# container, so that cleanup never happens when the container fails to start
# (bad image, no daemon, OOM, killed by the watchdog). Run N-1's clean report
# then stayed on disk and normalize.py counted the category as scanned and
# clean: a false all-clear for a scan that never ran. Doing the same rm on the
# host closes that window with no new state or file format — the report's
# presence keeps its plain meaning, "this run produced it".
#
# Only the category being re-run is cleared. A `--only <category>` rescan
# deliberately relies on the other categories' reports persisting from the
# previous full run, so a blanket wipe of .appsec-results would turn every
# scoped rescan into three fresh coverage gaps — a false alarm on every clean
# fix-loop iteration.
clear_stale_reports() {
  # A dry run plans; it must never delete the last real scan's results.
  if $DRY_RUN; then return 0; fi
  case "$1" in
    sast)
      rm -f .appsec-results/fortify-sast.fpr .appsec-results/fortify-sast-*.fpr .appsec-results/sast-units
      ;;
    dependency_scanning)
      # dependency-sbom-scan-*.json is derived from these SBOMs and counts as
      # dependency evidence too, so it goes with them.
      rm -f .appsec-results/gl-sbom-*.cdx.json \
            .appsec-results/gl-dependency-scanning-report.json \
            .appsec-results/dependency-sbom-scan-*.json
      ;;
    secret_detection)
      rm -f .appsec-results/gl-secret-detection-report.json
      ;;
    container_scanning)
      # NOT gl-sbom-*.cdx.json: GTCS writes the image SBOM under the same glob
      # dependency scanning uses, and container scanning runs after DS in a full
      # scan — clearing it here would delete this run's dependency evidence.
      rm -f .appsec-results/gl-container-scanning-report.json \
            .appsec-results/container-scan-archive.json
      ;;
  esac
}

# Resolve every enabled category's image BEFORE the missing-image checks below,
# so a category that legitimately omits image: (deriving it from the component)
# is not mistaken for one whose image was left unset by accident.
#
# template-image reads only local cache or vendored snapshots. During --dry-run,
# resolve-image adopts the same candidate without pulling it from the registry.
image_pull_mode=pull
if $DRY_RUN; then
  image_pull_mode=no-pull
fi

category_image_var() {
  case "$1" in
    sast) printf 'FORTIFY_SAST_IMAGE' ;;
    dependency_scanning) printf 'GITLAB_DS_IMAGE' ;;
    secret_detection) printf 'SECRET_DETECTION_IMAGE' ;;
    container_scanning) printf 'GITLAB_CS_IMAGE' ;;
  esac
}

category_run_flag() {
  case "$1" in
    sast) printf 'RUN_FORTIFY_SAST' ;;
    dependency_scanning) printf 'RUN_GITLAB_DS' ;;
    secret_detection) printf 'RUN_SECRET_DETECTION' ;;
    container_scanning) printf 'RUN_GITLAB_CS' ;;
  esac
}

category_scanner_name() {
  case "$1" in
    sast) printf 'Fortify SCA' ;;
    dependency_scanning) printf 'GitLab DS' ;;
    secret_detection) printf 'Secret Detection' ;;
    container_scanning) printf 'GitLab CS' ;;
  esac
}

# The component path comes from ENABLED_COMPONENTS (the admin's config), never
# from a literal table here. The table this replaced hardcoded
# lobster-thermidor/... paths, so an admin who repointed component: still had
# their image resolved from the OLD component — and silently: catalog.sh falls
# back to reference/catalog/<hardcoded path>, whose vendored snapshot yields
# registry.gitlab.com/security-products/container-scanning:8.6.31. On an
# internet-connected instance that pull SUCCEEDS, so the scan runs the PUBLIC
# analyzer instead of the configured internal mirror and nothing says so.
#
# Which Fortify JDK variant this project needs. Detected here rather than left to
# config because the component's default (jdk17-review) silently under-builds a
# Java 21 project, and asking every admin to hand-pin an image per repository is
# the kind of manual step that never happens. Same shape as FORTIFY_LANGUAGE
# below: auto-detected, overridable by the environment.
#
# The release comes from the codebase; which variants exist comes from the
# component's checked-in contract, never from a literal list here. That is the
# half this skill kept getting wrong: fortify-sast.contract has recorded
# input.variant.option=jdk21-review all along while nothing consumed it. Read it,
# and a future jdk25-review starts being selected by the contract regeneration
# that a component bump already requires.
#
# Not a Java project, or no release declared anywhere: stay empty and leave every
# existing path untouched.
if [ -z "${FORTIFY_VARIANT:-}" ]; then
  detected_release=$(sh "$SCRIPTS_DIR/detect-java-release.sh" . 2>/dev/null || true)
  if [ -n "$detected_release" ]; then
    # Which variants exist is taken from the component as resolved THIS RUN, so a
    # platform team publishing jdk25-review reaches every developer without an MR
    # here — the same way `version: ~latest` already rolls out a new component
    # version. The checked-in contract is the offline fallback, not the gate;
    # check-drift still reports the change either way.
    sast_component=
    sast_runner=
    for tuple in ${ENABLED_COMPONENTS:-}; do
      case "$tuple" in
        *'|sast')
          sast_component=${tuple%%|*}
          sast_rest=${tuple#*|}          # version|runner|image|category
          sast_rest=${sast_rest#*|}      # runner|image|category
          sast_runner=${sast_rest%%|*}
          ;;
      esac
    done
    # Derived from the configured runner, never a literal filename: `runner:` is an
    # admin override, and catalog.sh pairs a runner with its contract the same way.
    variant_contract="$SCANNERS_DIR/${sast_runner:-fortify-sast.sh}"
    variant_contract="${variant_contract%.sh}.contract"
    if [ -n "$sast_component" ]; then
      live_contract="${CATALOG_CACHE:-.appsec-results/catalog}/fortify-variant.contract"
      mkdir -p "$(dirname "$live_contract")" 2>/dev/null || true
      if bash "$SCRIPTS_DIR/catalog.sh" contract "$sast_component" \
           "${CATALOG_CACHE:-.appsec-results/catalog}" >"$live_contract" 2>/dev/null &&
         grep -q '^input\.variant\.option=' "$live_contract" 2>/dev/null; then
        variant_contract=$live_contract
      fi
    fi
    FORTIFY_VARIANT=$(sh "$SCRIPTS_DIR/select-jdk-variant.sh" "$detected_release" \
                        "$variant_contract" 2>/dev/null || true)
    if [ -n "$FORTIFY_VARIANT" ]; then
      selected_jdk=$(printf '%s' "$FORTIFY_VARIANT" | sed -n 's/^jdk\([0-9][0-9]*\).*/\1/p')
      info "[Fortify SCA] Project targets Java ${detected_release}; selecting ${FORTIFY_VARIANT}"
      # CI does not detect this — the component takes `variant` as an input and
      # defaults it. So whenever we pick something other than that default, the
      # pipeline is about to scan this project with a different JDK than we just
      # did. Print the exact line to paste, while the developer is already here.
      default_variant=$(grep '^input\.variant\.default=' "$variant_contract" 2>/dev/null |
                          head -1 | sed 's/^[^=]*=//')
      if [ -n "$default_variant" ] && [ "$default_variant" != "$FORTIFY_VARIANT" ]; then
        info "[Fortify SCA] CI defaults to ${default_variant}. Add 'variant: ${FORTIFY_VARIANT}' to your SAST component inputs in .gitlab-ci.yml so the pipeline matches this scan."
      fi
      # Nothing published is new enough. Say so: the build may fail on syntax the
      # analyzer's JDK does not accept, and that is a component gap, not a bug here.
      if [ -n "$selected_jdk" ] && [ "$selected_jdk" -lt "$detected_release" ] 2>/dev/null; then
        warning "[Fortify SCA] The component publishes no JDK ${detected_release} variant; ${FORTIFY_VARIANT} is the newest offered. Ask the component maintainers to publish one."
      fi
    fi
  fi
fi
FORTIFY_VARIANT="${FORTIFY_VARIANT:-}"

# Word-splitting the tuple list is intentional and safe: this file is bash and
# load-prefs.sh emits space-separated tuples with no spaces inside one.
for tuple in ${ENABLED_COMPONENTS:-}; do
  # component|version|runner|image|category — take the ends, skip the middle.
  comp=${tuple%%|*}
  rest=${tuple#*|}   # version|runner|image|category
  rest=${rest#*|}    # runner|image|category
  rest=${rest#*|}    # image|category
  cat_name=${rest#*|}

  var=$(category_image_var "$cat_name")
  run_flag=$(category_run_flag "$cat_name")
  if [ -z "$var" ] || [ -z "$run_flag" ]; then
    warning "ignoring component $comp: unknown category '$cat_name'"
    continue
  fi

  eval "flag_value=\${$run_flag:-false}"
  [ "$flag_value" = true ] || continue
  # container_scanning's image is not only a scanner here — it is also the TOOL
  # that matches the dependency SBOM against its bundled advisory DB. So
  # `--only dependency_scanning`, which is exactly the rescan SKILL.md's fix loop
  # runs after fixing a dependency, still needs it resolved. Without this the
  # match degraded every time and the rescan reported the dependency findings
  # gone rather than fixed.
  if ! selected "$cat_name"; then
    { [ "$cat_name" = container_scanning ] && selected dependency_scanning; } || continue
  fi

  eval "configured=\${$var:-}"
  tmpl=$(bash "$SCRIPTS_DIR/catalog.sh" template-image "$comp" \
    "${CATALOG_CACHE:-.appsec-results/catalog}" 2>/dev/null || true)

  # Only SAST's image carries a JDK variant; the other categories' tags do not,
  # and resolve-image.sh would find nothing to substitute anyway.
  preferred_variant=
  [ "$cat_name" = sast ] && preferred_variant=$FORTIFY_VARIANT

  if effective=$(bash "$SCRIPTS_DIR/resolve-image.sh" \
      "$configured" "$tmpl" "$RUNTIME" "${IMAGE_POLICY:-follow-component}" \
      "$image_pull_mode" "$preferred_variant"); then
    [ -n "$effective" ] && eval "$var=\$effective"
  else
    record_missing_image "$(category_scanner_name "$cat_name")" "$var" "$cat_name"
    error "[$cat_name] could not resolve a scanner image; refusing to continue"
    error "  A scanner whose image cannot be determined must not be silently skipped —"
    error "  that would report a clean scan for a category that never ran."
    exit 2
  fi
done

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
# Captured BEFORE the default is applied: an explicitly chosen source path or
# language pins the scan to exactly one unit (today's behaviour, and the
# documented override), while the absence of both is what licenses discovery.
SAST_PINNED=false
{ [ -n "${SOURCE_PATH:-}" ] || [ -n "${FORTIFY_LANGUAGE:-}" ]; } && SAST_PINNED=true
SOURCE_PATH="${SOURCE_PATH:-src}"

HAS_POM=false
HAS_GRADLE=false
HAS_PACKAGE_JSON=false
HAS_REQUIREMENTS=false
HAS_DOCKERFILE=false
HAS_GO=false
[ -f pom.xml ] && HAS_POM=true
{ [ -f build.gradle ] || [ -f build.gradle.kts ]; } && HAS_GRADLE=true
[ -f package.json ] && HAS_PACKAGE_JSON=true
{ [ -f requirements.txt ] || [ -f pyproject.toml ]; } && HAS_REQUIREMENTS=true
[ -f Dockerfile ] && HAS_DOCKERFILE=true
[ -f go.mod ] && HAS_GO=true
HAS_POM_NO_GRADLE=false
{ $HAS_POM && ! $HAS_GRADLE; } && HAS_POM_NO_GRADLE=true

info "Project: $APP_NAME  Branch: $BRANCH"
info "Detected: Maven=$HAS_POM Gradle=$HAS_GRADLE NPM=$HAS_PACKAGE_JSON Python=$HAS_REQUIREMENTS Go=$HAS_GO Dockerfile=$HAS_DOCKERFILE HAS_POM_NO_GRADLE=$HAS_POM_NO_GRADLE"
mkdir -p .appsec-results
grep -qxF '.appsec-results/' .gitignore 2>/dev/null || \
  info ".appsec-results/ is self-ignoring (it contains its own .gitignore); no change to your repo's .gitignore is needed"

# This run OWNS the results of every category it is about to attempt, so their
# previous reports go now — before any precondition below can bail out. Doing it
# here, once, rather than inside each scanner's launch path means no branch can
# forget it: the paths that bail early (no Dockerfile, no supported language, not
# a Git worktree) are exactly the ones a stale report used to survive.
for stale_category in sast dependency_scanning secret_detection container_scanning; do
  selected "$stale_category" || continue
  stale_flag=$(category_run_flag "$stale_category")
  eval "stale_enabled=\${$stale_flag:-false}"
  [ "$stale_enabled" = true ] || continue
  clear_stale_reports "$stale_category"
done

# ponytail: RUN_* values are data; only the literal string true enables a scanner.
if selected sast && [ "$RUN_FORTIFY_SAST" = true ] && [ -n "$FORTIFY_SAST_IMAGE" ]; then
  # Fortify is a per-build-tree scanner: CI includes the component once per
  # service, each with its own source-path. One detected language and one path
  # cannot represent a repository that has several, so the units are discovered
  # — and every one of them is recorded as expected coverage, exactly the rule
  # `--only` follows. Narrowing what RUNS must never narrow what is EXPECTED.
  SAST_UNITS_FILE=.appsec-results/sast-units
  : >"$SAST_UNITS_FILE"
  if $SAST_PINNED; then
    if [ -z "${FORTIFY_LANGUAGE:-}" ]; then
      if $HAS_GRADLE; then FORTIFY_LANGUAGE=gradle
      elif $HAS_POM; then FORTIFY_LANGUAGE=maven
      elif $HAS_REQUIREMENTS; then FORTIFY_LANGUAGE=python
      elif $HAS_PACKAGE_JSON; then FORTIFY_LANGUAGE=javascript
      elif $HAS_GO; then FORTIFY_LANGUAGE=go
      fi
    fi
    [ -z "${FORTIFY_LANGUAGE:-}" ] || printf '%s|%s\n' "$SOURCE_PATH" "$FORTIFY_LANGUAGE" >"$SAST_UNITS_FILE"
  else
    sh "$SCRIPTS_DIR/detect-sast-units.sh" . >"$SAST_UNITS_FILE" 2>/dev/null || :
  fi

  SAST_UNIT_COUNT=$(grep -c '|' "$SAST_UNITS_FILE" 2>/dev/null || echo 0)
  if [ "$SAST_UNIT_COUNT" -eq 0 ]; then
    info "[Fortify SCA] No supported project type detected; skipping"
    record_skip sast "Fortify found no supported project type (maven/gradle/python/javascript/go) anywhere in this repository, so SAST did NOT run and your source was never analysed. Set FORTIFY_LANGUAGE explicitly, or add the matching build manifest, then re-run this skill."
    RUN_FORTIFY_SAST=false
  else
    info "[Fortify SCA] $SAST_UNIT_COUNT unit(s) to scan:"
    while IFS='|' read -r u_path u_lang; do
      [ -n "$u_path" ] || continue
      info "  - $u_path ($u_lang)"
    done <"$SAST_UNITS_FILE"
  fi
  if [ "$RUN_FORTIFY_SAST" = true ]; then
    mark_attempted sast
    mark_executed sast
    info "[Fortify SCA] Pulling ${FORTIFY_SAST_IMAGE}..."
    if pull_image sast "Fortify SCA" "${FORTIFY_SAST_IMAGE}" "SAST did NOT run and your source was never analysed."; then
      if $DRY_RUN; then
        while IFS='|' read -r u_path u_lang; do
          [ -n "$u_path" ] || continue
          print_dry_run "$RUNTIME" run --rm -v "$PWD:/workspace" -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} ${MAVEN_MOUNT_ARGS[@]+"${MAVEN_MOUNT_ARGS[@]}"} -w /workspace -e APP_NAME="$APP_NAME" -e FORTIFY_BUILD_ID="$APP_NAME-$(unit_slug "$u_path")" -e FPR_NAME="$(unit_fpr "$u_path")" -e SOURCE_PATH="$u_path" -e FORTIFY_LANGUAGE="$u_lang" -e MAVEN_SETTINGS="$MAVEN_SETTINGS_PATH" -e UV_VERSION="${UV_VERSION:-}" -e UV_INSTALLER_BASE="${UV_INSTALLER_BASE:-}" -e UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-}" -e UV_DEFAULT_INDEX="${APPSEC_PIP_INDEX_URL:-}" -e PIP_INDEX_URL="${APPSEC_PIP_INDEX_URL:-}" -e FORTIFY_PYTHON_VERSION="${FORTIFY_PYTHON_VERSION:-}" -e FORTIFY_PYTHON_TEMPLATE_DIRS="${FORTIFY_PYTHON_TEMPLATE_DIRS:-}" -e ARTIFACTORY_USER="$(printenv "$ARTIFACTORY_USER_ENV" 2>/dev/null || true)" -e ARTIFACTORY_PASSWORD="$(printenv "$ARTIFACTORY_PASSWORD_ENV" 2>/dev/null || true)" "${FORTIFY_SAST_IMAGE}" sh /runner.sh
        done <"$SAST_UNITS_FILE"
      else
        # Units run sequentially inside ONE background job: a Fortify container
        # is heavy, and N of them at once starves the other scanners this
        # backgrounding exists to overlap with. The whole group keeps a single
        # PID and a single watchdog, so timeout handling is unchanged.
        (
          group_rc=0
          unit_pid=
          stopped=false
          # start_watchdog signals THIS subshell, not the container, so the
          # escalation has to be repeated one level down. Forwarding only TERM is
          # not enough: the subshell would exit first, the outer KILL would find
          # nothing left to kill, and a TERM-ignoring scanner would be orphaned
          # and run forever — the exact fail-open the watchdog exists to close.
          # The 1s grace is deliberately shorter than start_watchdog's 2s, so the
          # container is dead before the outer KILL arrives. Stop afterwards too:
          # the remaining units belong to a run that has been abandoned.
          trap 'stopped=true
                if [ -n "$unit_pid" ]; then
                  kill -TERM "$unit_pid" 2>/dev/null || true
                  sleep 1
                  kill -KILL "$unit_pid" 2>/dev/null || true
                fi' TERM
          while IFS='|' read -r u_path u_lang; do
            [ -n "$u_path" ] || continue
            if $stopped; then break; fi
            echo "=== Fortify unit: $u_path ($u_lang) ==="
            "$RUNTIME" run --rm \
              -v "$PWD:/workspace" \
              -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" \
              ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
              ${MAVEN_MOUNT_ARGS[@]+"${MAVEN_MOUNT_ARGS[@]}"} \
              -w /workspace \
              -e APP_NAME="$APP_NAME" \
              -e FORTIFY_BUILD_ID="$APP_NAME-$(unit_slug "$u_path")" \
              -e FPR_NAME="$(unit_fpr "$u_path")" \
              -e SOURCE_PATH="$u_path" \
              -e FORTIFY_LANGUAGE="$u_lang" \
              -e MAVEN_SETTINGS="$MAVEN_SETTINGS_PATH" \
              -e UV_VERSION="${UV_VERSION:-}" \
              -e UV_INSTALLER_BASE="${UV_INSTALLER_BASE:-}" \
              -e UV_PYTHON_INSTALL_MIRROR="${UV_PYTHON_INSTALL_MIRROR:-}" \
              -e UV_DEFAULT_INDEX="${APPSEC_PIP_INDEX_URL:-}" \
              -e PIP_INDEX_URL="${APPSEC_PIP_INDEX_URL:-}" \
              -e FORTIFY_PYTHON_VERSION="${FORTIFY_PYTHON_VERSION:-}" \
              -e FORTIFY_PYTHON_TEMPLATE_DIRS="${FORTIFY_PYTHON_TEMPLATE_DIRS:-}" \
              -e ARTIFACTORY_USER="$(printenv "$ARTIFACTORY_USER_ENV" 2>/dev/null || true)" \
              -e ARTIFACTORY_PASSWORD="$(printenv "$ARTIFACTORY_PASSWORD_ENV" 2>/dev/null || true)" \
              "${FORTIFY_SAST_IMAGE}" \
              sh /runner.sh &
            # Backgrounded so the TERM trap above can reach it: with the
            # container in the foreground the trap does not run until it exits,
            # which for a hung scan is never.
            unit_pid=$!
            wait "$unit_pid" || group_rc=1
            unit_pid=
          done <"$SAST_UNITS_FILE"
          exit "$group_rc"
        ) > .appsec-results/fortify-sast.log 2>&1 &
        FORTIFY_SAST_PID=$!
        start_watchdog "$FORTIFY_SAST_PID"
        FORTIFY_SAST_WATCHDOG=$WATCHDOG_PID
      fi
    fi
  fi
fi

if selected dependency_scanning && [ "$RUN_GITLAB_DS" = true ] && [ -n "$GITLAB_DS_IMAGE" ]; then
  DS_RAN=true
  mark_attempted dependency_scanning
  mark_executed dependency_scanning
  info "[GitLab DS] Pulling ${GITLAB_DS_IMAGE}..."
  if pull_image dependency_scanning "GitLab DS" "${GITLAB_DS_IMAGE}" "dependency scanning did NOT run."; then
    if $DRY_RUN; then
      print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-dependency-scanning.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} ${MAVEN_MOUNT_ARGS[@]+"${MAVEN_MOUNT_ARGS[@]}"} -w /workspace -e CI_PROJECT_DIR=/workspace -e GITLAB_FEATURES=dependency_scanning ${DS_AIRGAP_ARGS[@]+"${DS_AIRGAP_ARGS[@]}"} "${GITLAB_DS_IMAGE}" sh /runner.sh
    else
      "$RUNTIME" run --rm \
        --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/gitlab-dependency-scanning.sh:/runner.sh:ro" \
        ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
        ${MAVEN_MOUNT_ARGS[@]+"${MAVEN_MOUNT_ARGS[@]}"} \
        -w /workspace \
        -e CI_PROJECT_DIR="/workspace" \
        -e GITLAB_FEATURES="dependency_scanning" \
        ${DS_AIRGAP_ARGS[@]+"${DS_AIRGAP_ARGS[@]}"} \
        "${GITLAB_DS_IMAGE}" \
        sh /runner.sh > .appsec-results/gitlab-ds.log 2>&1 &
      GITLAB_DS_PID=$!
      start_watchdog "$GITLAB_DS_PID"
      GITLAB_DS_WATCHDOG=$WATCHDOG_PID
    fi
  fi
fi

if selected secret_detection && [ "$RUN_SECRET_DETECTION" = true ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ -n "$SECRET_DETECTION_IMAGE" ]; then
  mark_attempted secret_detection
  mark_executed secret_detection
  info "[Secret Detection] Pulling ${SECRET_DETECTION_IMAGE}..."
  if pull_image secret_detection "Secret Detection" "${SECRET_DETECTION_IMAGE}" "secret detection did NOT run."; then
    if $DRY_RUN; then
      print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/secret-detection.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} -w /workspace -e CI_PROJECT_DIR=/workspace -e GIT_DEPTH="${GIT_DEPTH:-50}" -e SECRET_DETECTION_EXCLUDED_PATHS="${SECRET_DETECTION_EXCLUDED_PATHS:-}" "${SECRET_DETECTION_IMAGE}" sh /runner.sh
    else
      "$RUNTIME" run --rm \
        --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/secret-detection.sh:/runner.sh:ro" \
        ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
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
  fi
elif selected secret_detection && [ "$RUN_SECRET_DETECTION" = true ]; then
  info "[Secret Detection] Skipped — not a Git worktree or image unset"
  record_skip secret_detection "Secret detection needs a Git worktree (it scans history), and this directory is not one — or its image is unset. Run the scan from inside the repository, then re-run this skill."
fi

# A glob, not `ls`. These hosts have a stripped PATH, and an `ls` that cannot be
# resolved answers "no SBOM" to both callers below: the first invents a
# lock-file gap that is not there, the second skips the vulnerability match with
# nothing recording that it was skipped. A glob has nothing to fail — when
# nothing matches, the pattern stays literal and -e finds it absent.
sbom_present() {
  set -- .appsec-results/gl-sbom-*.cdx.json
  [ -e "$1" ]
}

if ! $DRY_RUN; then
  info "Waiting for parallel scanners..."
  for pid_var in FORTIFY_SAST_PID GITLAB_DS_PID SECRET_DETECTION_PID; do
    pid="${!pid_var:-}"
    if [ -n "$pid" ]; then
      if wait "$pid"; then
        info "[${pid_var/_PID/}] Done"
      else
        rc=$?
        # A scanner that failed produced no result for its category, so record
        # the gap. Warning alone is prose no caller parses: the category still
        # counted as covered, and whatever report happened to be on disk (run
        # N-1's, before clear_stale_reports) was read as this run's clean result.
        case "$pid_var" in
          FORTIFY_SAST_PID)
            failed_category=sast
            failed_log=.appsec-results/fortify-sast.log
            ;;
          GITLAB_DS_PID)
            failed_category=dependency_scanning
            failed_log=.appsec-results/gitlab-ds.log
            DS_FAILED=true
            ;;
          *)
            failed_category=secret_detection
            failed_log=.appsec-results/secret-detection.log
            ;;
        esac
        if [ "$pid_var" = "GITLAB_DS_PID" ] && [ "$rc" -eq 2 ]; then
          warning "[GITLAB_DS] Local run unsupported by this analyzer — run Dependency Scanning in the CI pipeline"
          record_skip dependency_scanning "This analyzer cannot run dependency scanning locally (exit 2), so no dependency was analysed here. Run Dependency Scanning in the CI pipeline for this category; details in $failed_log."
        else
          warning "[${pid_var/_PID/}] Failed (exit $rc) — check $failed_log"
          record_skip "$failed_category" "The $failed_category scanner exited $rc, so it did NOT complete and this category was not scanned. Read $failed_log for the cause (unusable image, container runtime, memory, timeout), fix it, then re-run this skill."
        fi
      fi
      watchdog_var="${pid_var%_PID}_WATCHDOG"
      watchdog_pid="${!watchdog_var:-}"
      [ -z "$watchdog_pid" ] || wait "$watchdog_pid" 2>/dev/null || true
    fi
  done

  # Per-unit accounting. The group's exit code says "something failed"; only the
  # reports say WHICH source paths were actually analysed. Without this, three
  # units out of four succeeding left a category with reports on disk — covered,
  # and silent about the service nobody scanned.
  if [ -s "${SAST_UNITS_FILE:-/dev/null}" ]; then
    unscanned=
    while IFS='|' read -r u_path u_lang; do
      [ -n "$u_path" ] || continue
      [ -f ".appsec-results/$(unit_fpr "$u_path")" ] || unscanned="$unscanned $u_path($u_lang)"
    done <"$SAST_UNITS_FILE"
    if [ -n "$unscanned" ]; then
      warning "[Fortify SCA] No report for:$unscanned"
      record_skip sast "Fortify produced no report for:$unscanned — that source was NOT analysed, even though other units in this repository were. Read .appsec-results/fortify-sast.log for the per-unit cause, fix it, then re-run this skill."
    fi
    # A python unit that resolved no third-party imports still produces a report,
    # so this is NOT a coverage gap — the scanner ran. It is a scan that finds
    # less than CI will (upstream measured 28 vs 46 on the same code), which is
    # exactly the kind of quiet shortfall this skill exists to surface.
    if grep -q '^APPSEC-PY-DEGRADED:' .appsec-results/fortify-sast.log 2>/dev/null; then
      warning "[Fortify SCA] Python resolution was DEGRADED — third-party imports were not resolved,"
      warning "  so this scan finds less than CI will. It is not a coverage gap: the scanner ran."
      warning "  Fix: set settings.python_runtime.{uv_version,uv_installer_base,uv_python_install_mirror}"
      warning "  to your internal mirror. Details in .appsec-results/fortify-sast.log"
    fi
  fi

  # The analyzer exits 0 when it simply finds no lock file, so a non-zero rc is
  # not the signal — the absence of a report is. Name the real cause instead of
  # leaving the generic "expected a report and did not" text.
  # Only when the analyzer actually finished. load_skip_reasons keeps the LAST
  # skip per category, so on a crashed analyzer this line would overwrite the
  # real reason and send the user hunting for a lock file they already have.
  if [ -n "${GITLAB_DS_PID:-}" ] && [ "$DS_FAILED" = false ] && ! sbom_present \
     && [ ! -s .appsec-results/gl-dependency-scanning-report.json ]; then
    record_skip dependency_scanning "The dependency analyzer produced no SBOM: it needs a lock file (package-lock.json, poetry.lock, a pip-compile requirements lock, go.sum...), not a plain manifest. Add one and re-run this skill, or rely on the CI pipeline for this category. Details: .appsec-results/gitlab-ds.log"
  fi
fi

# Dependency Scanning run locally emits an SBOM and NOTHING else: GitLab matches
# it server-side, behind an API that accepts only a real CI_JOB_TOKEN. An SBOM
# normalizes to zero findings, so on its own the category reads as "scanned,
# clean" while nothing was ever compared against an advisory — and any finding
# that does arrive carries no fixed_version, which is what the registry-gap
# remediation and the fix loop run on. Trivy is bundled in the CONTAINER
# SCANNING image (the DS image ships no scanner) with its advisory DB baked in,
# so this pass needs no network.
sbom_match_degraded() {
  warning "[DS SBOM] $1"
  warning "[DS SBOM] Dependency results stay SBOM-only — nothing was matched against advisories locally. That is NOT an all-clear for dependencies."
  record_skip dependency_scanning "Dependency scanning produced an SBOM, but the local vulnerability match did not run ($1), so no dependency vulnerability was matched here and findings carry no fixed_version. The bundled Trivy lives in the container-scanning image: enable container_scanning in scanner-preferences.yaml (or re-run without --only dependency_scanning), then re-run this skill. Until then the GitLab Vulnerability Report after push is the only dependency result."
}

# No SBOM => nothing to match, and the skip above already named the real cause
# (no lock file). Only an SBOM that exists but was never matched is a gap.
if selected dependency_scanning && [ "$DS_RAN" = true ] && \
   { $DRY_RUN || sbom_present; }; then
  if [ -z "$GITLAB_CS_IMAGE" ]; then
    sbom_match_degraded "no container-scanning image was resolved"
  elif $DRY_RUN; then
    print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/sbom-vuln-scan.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} -w /workspace -e CI_PROJECT_DIR=/workspace "${GITLAB_CS_IMAGE}" sh /runner.sh
  else
    info "[DS SBOM] Matching the SBOM against the advisory DB bundled in ${GITLAB_CS_IMAGE}..."
    if ! run_container_scan .appsec-results/sbom-vuln-scan.log "$RUNTIME" run --rm --entrypoint "" \
      -v "$PWD:/workspace" \
      -v "$SCANNERS_DIR/sbom-vuln-scan.sh:/runner.sh:ro" \
      ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
      -w /workspace \
      -e CI_PROJECT_DIR="/workspace" \
      "${GITLAB_CS_IMAGE}" \
      sh /runner.sh; then
      sbom_match_degraded "it failed — see .appsec-results/sbom-vuln-scan.log"
    fi
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
      # GTCS turns a base-image finding into a concrete "upgrade FROM to X"
      # remediation, but only when CS_DOCKERFILE_PATH names the Dockerfile
      # (the component declares the input and defaults it to "Dockerfile").
      # Nothing here ever set it, so that remediation never ran locally.
      CS_DOCKERFILE_ARGS=()
      cs_dockerfile=$(find_dockerfile || true)
      if [ -n "$cs_dockerfile" ]; then
        CS_DOCKERFILE_ARGS=(-e CS_DOCKERFILE_PATH="$cs_dockerfile")
      fi
      if pull_image container_scanning "GitLab CS" "${GITLAB_CS_IMAGE}" "container scanning did NOT run."; then
        if $DRY_RUN; then
          print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} -w /workspace -e CI_PROJECT_DIR=/workspace -e CS_SCAN_MODE=registry -e CS_IMAGE="$CS_VALUE" ${CS_DOCKERFILE_ARGS[@]+"${CS_DOCKERFILE_ARGS[@]}"} -e CS_REGISTRY_USER="$(printenv "$CS_USER_ENV" 2>/dev/null || true)" -e CS_REGISTRY_PASSWORD="$(printenv "$CS_PASS_ENV" 2>/dev/null || true)" "${GITLAB_CS_IMAGE}" sh /runner.sh
        elif run_container_scan .appsec-results/gitlab-cs.log "$RUNTIME" run --rm --entrypoint "" \
          -v "$PWD:/workspace" \
          -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
          ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
          -w /workspace \
          -e CI_PROJECT_DIR="/workspace" \
          -e CS_SCAN_MODE="registry" \
          -e CS_IMAGE="$CS_VALUE" \
          ${CS_DOCKERFILE_ARGS[@]+"${CS_DOCKERFILE_ARGS[@]}"} \
          -e CS_REGISTRY_USER="$(printenv "$CS_USER_ENV" 2>/dev/null || true)" \
          -e CS_REGISTRY_PASSWORD="$(printenv "$CS_PASS_ENV" 2>/dev/null || true)" \
          "${GITLAB_CS_IMAGE}" \
          sh /runner.sh; then
          GITLAB_CS_PID="ran"
        else
          warning "[GitLab CS] Scan failed — check .appsec-results/gitlab-cs.log"
          record_skip container_scanning "Container scanning failed while scanning $CS_VALUE, so the image was NOT scanned. Read .appsec-results/gitlab-cs.log for the cause (registry credentials, image reference, container runtime, timeout), fix it, then re-run this skill."
        fi
      fi
      ;;
    archive)
      mark_attempted container_scanning
      mark_executed container_scanning
      info "[GitLab CS] Scanning locally-built image (offline, bundled Trivy)..."
      if pull_image container_scanning "GitLab CS" "${GITLAB_CS_IMAGE}" "container scanning did NOT run."; then
        if $DRY_RUN; then
          print_dry_run "$RUNTIME" run --rm --entrypoint "" -v "$PWD:/workspace" -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" ${CA_ARGS[@]+"${CA_ARGS[@]}"} -w /workspace -e CI_PROJECT_DIR=/workspace -e CS_SCAN_MODE=archive -e CS_ARCHIVE=/workspace/.appsec-results/container-image.tar "${GITLAB_CS_IMAGE}" sh /runner.sh
        elif run_container_scan .appsec-results/gitlab-cs.log "$RUNTIME" run --rm --entrypoint "" \
          -v "$PWD:/workspace" \
          -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
          ${CA_ARGS[@]+"${CA_ARGS[@]}"} \
          -w /workspace \
          -e CI_PROJECT_DIR="/workspace" \
          -e CS_SCAN_MODE="archive" \
          -e CS_ARCHIVE="/workspace/.appsec-results/container-image.tar" \
          "${GITLAB_CS_IMAGE}" \
          sh /runner.sh; then
          GITLAB_CS_PID="ran"
        else
          warning "[GitLab CS] Scan failed — check .appsec-results/gitlab-cs.log"
          record_skip container_scanning "Container scanning failed on the locally-built image archive, so the image was NOT scanned. Read .appsec-results/gitlab-cs.log for the cause (image build, container runtime, memory, timeout), fix it, then re-run this skill."
        fi
      fi
      ;;
    error)
      # No target means no scan. Unrecorded, this branch left container_scanning
      # counted as covered — clean if any older report was still on disk.
      #
      # container-target.sh already tells a base-image pull failure apart from a
      # broken build and prints the remedy for each. Reading CS_VALUE keeps that
      # distinction: collapsing both into one message sent people to raise a
      # ticket for a missing `docker login`.
      if [ "$CS_VALUE" = base-pull ]; then
        record_config_error container_scanning "The Dockerfile's FROM base image could not be pulled from the registry, so container scanning did NOT run. Log in to the registry, or set the credentials named by settings.container_registry in scanner-preferences.yaml, and point FROM at the internal mirror — the exact commands are printed above. Details: .appsec-results/container-build.log"
      else
        warning "[GitLab CS] Could not prepare a scan target (see container-target.sh output above)."
        record_skip container_scanning "The container-scanning target could not be prepared (the image could not be built or saved), so container scanning did NOT run. Fix the build/save error reported above, then re-run this skill."
      fi
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

# Ask the mirror which suggested upgrades are actually obtainable, so the fix loop
# never spends one of its five iterations on a version we cannot fetch. Needs a
# first normalize pass to know the packages, so this runs between two passes; the
# second pass folds the answers into remediation_status. No registries configured
# (the shipped default) => probe writes an empty map and pass 2 is skipped entirely.
AVAILABILITY_ARGS=""
run_normalize() {
  if [ -n "$ONLY_CATEGORY" ]; then
    # AVAILABILITY_ARGS is an intentional word list, not one argument.
    # shellcheck disable=SC2086
    "$PY_BIN" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE" --only "$ONLY_CATEGORY" $AVAILABILITY_ARGS
  else
    # shellcheck disable=SC2086
    "$PY_BIN" "$SCRIPTS_DIR/normalize.py" .appsec-results --gate "${CI_GATE_FAIL_ON:-high}" --ran "$RAN_CATEGORIES" --skips "$SKIPS_FILE" $AVAILABILITY_ARGS
  fi
}

# Probing needs a configured registry URL. Without one the first pass IS the only
# pass — its output is already on stdout and its exit code is the gate.
probe_configured() {
  printf '%s' "${PACKAGE_REGISTRIES:-}" | grep -q '[a-zA-Z]://'
}

if [ -n "$PY_BIN" ]; then
  if probe_configured; then
    # Pass 1 is discarded output — it exists only so check-remediation.py can see
    # which packages and fixed versions the scanners actually reported.
    set +e
    run_normalize >/dev/null 2>&1
    # The probe's own stderr used to go to /dev/null with it, so a mirror that
    # refused every request could say so and nobody would ever hear it. Keep the
    # probe non-fatal (set +e), but let it be heard.
    "$PY_BIN" "$SCRIPTS_DIR/check-remediation.py" .appsec-results \
      --registries "${PACKAGE_REGISTRIES:-}" \
      --token-env "${PACKAGE_REGISTRY_AUTH_ENV:-}" \
      2> .appsec-results/remediation-probe.log
    set -e
    while IFS= read -r probe_line; do
      case "$probe_line" in
        CONFIG-ERROR:\ *) record_config_error "" "${probe_line#CONFIG-ERROR: }" ;;
        *) printf '%s\n' "$probe_line" >&2 ;;
      esac
    done < .appsec-results/remediation-probe.log
    [ -f .appsec-results/registry-availability.json ] && \
      AVAILABILITY_ARGS="--availability .appsec-results/registry-availability.json"
  fi

  set +e
  run_normalize
  gate_rc=$?
  set -e
  report_config_errors
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

# Without normalize.py nothing was assessed: no triage, no gate, no coverage
# record. This used to `exit 0` and write no scan-coverage.json at all, so a CI
# step reading the exit code got a clean pass with nothing machine-readable to
# contradict it — the warnings above are prose no caller parses. Write the
# record the normalizer would have written, with every expected category
# unassessed, AND exit non-zero. Either alone is missable.
case "${CI_GATE_FAIL_ON:-high}" in
  critical|high|medium|none) gate_threshold=${CI_GATE_FAIL_ON:-high} ;;
  *) gate_threshold=high ;;
esac
# Category names are the fixed identifiers from mark_attempted, so no escaping.
missing_json=
rest=$RAN_CATEGORIES
while [ -n "$rest" ]; do
  case "$rest" in
    *,*) item=${rest%%,*}; rest=${rest#*,} ;;
    *)   item=$rest; rest= ;;
  esac
  [ -n "$item" ] || continue
  if [ -n "$missing_json" ]; then
    missing_json="$missing_json,\"$item\""
  else
    missing_json="\"$item\""
  fi
done
# scanners_run stays empty: no report was read, so nothing is accounted for.
# Claiming these as run would let a later scoped rescan union them in as covered.
cat > .appsec-results/scan-coverage.json <<EOF
{
  "scanners_run": [],
  "missing_report": [$missing_json],
  "gate_threshold": "$gate_threshold",
  "gate_passed": false,
  "coverage_complete": false,
  "reason": "python3 unavailable: findings were never normalized, triaged or gated"
}
EOF
report_config_errors
error "findings were never assessed (python3 unavailable) — this run is NOT a pass"
exit 2

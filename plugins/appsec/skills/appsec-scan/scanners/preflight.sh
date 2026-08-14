#!/usr/bin/env bash
# Preflight checks for appsec-scan.
# Run this script at the start of a scan run:
#   bash "$SCANNERS_DIR/preflight.sh"
# Fails fast with a clear message if required vars are missing.
set -euo pipefail

_uname=$(uname -s 2>/dev/null || echo Unknown)
case "$_uname" in
  MINGW*|MSYS*|CYGWIN*)
    echo 'INFO: Native Windows Git Bash/MSYS detected. WSL2 is the supported path for full Docker volume mounts and sandboxing. Proceeding in best-effort mode.' >&2
    ;;
esac

ERRORS=()

# A named token var is always required: resolution is always attempted online,
# and a tokenless run would degrade to the vendored snapshots while looking like
# a live check. Profiles on instances that allow anonymous reads set
# auth_token_env: "" and skip this entirely.
if [ -n "${CATALOG_AUTH_ENV:-}" ]; then
  catalog_auth_value="$(printenv "$CATALOG_AUTH_ENV" 2>/dev/null || true)"
  [ -z "$catalog_auth_value" ] && \
    ERRORS+=("catalog auth: env var $CATALOG_AUTH_ENV (named by settings.catalog.auth_token_env) is not set")
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Self-load preferences when the caller passed only the catalog vars, so the
# checks below need no new arguments in SKILL.md Step 2. Same pattern as
# run-scan.sh: the config is the single source, never inferred.
if [ -z "${PACKAGE_REGISTRIES+x}" ]; then
  eval "$(bash "$SKILL_DIR/scripts/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml")"
fi
# --require-daemon: binary presence is not a usable environment. Without this,
# a wedged Docker Desktop sailed through preflight and failed later as a hanging
# pull, contradicting "never start scanners against an incomplete environment".
if ! RT="$(CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-}" "$SKILL_DIR/scripts/detect-runtime.sh" --require-daemon 2>&1)"; then
  ERRORS+=("container runtime unusable: ${RT#ERROR: }")
fi

# ponytail: normalize unset to empty before trimming a trailing slash under set -u.
gitlab_instance="${GITLAB_INSTANCE:-}"
if [ "${APPSEC_AIRGAP:-}" = "true" ] && [ "${gitlab_instance%/}" = "https://gitlab.com" ]; then
  ERRORS+=("profile '${APPSEC_PROFILE:-catalog}' targets gitlab.com and is not allowed when airgap=true")
fi

# A path that is configured but unreadable fails every scanner request from
# inside the container, and does it in a way that reads like a network outage
# rather than a trust problem — which is why it used to cost a day to diagnose.
# It was a mid-run warning; the whole point of preflight is to catch it before
# any container starts. Empty (the shipped default) means disabled, not broken.
if [ -n "${CA_BUNDLE:-}" ] && [ ! -r "$CA_BUNDLE" ]; then
  ERRORS+=("settings.ca_bundle points at $CA_BUNDLE, which is not readable here")
fi
if [ -n "${MAVEN_SETTINGS:-}" ] && [ ! -r "$MAVEN_SETTINGS" ]; then
  ERRORS+=("settings.maven_settings points at $MAVEN_SETTINGS, which is not readable here")
fi

# Ask each configured package registry one question, before the scan rather than
# after it. Only a refusal is an error: 404 for a package nobody has published is
# the healthy answer, and an unreachable registry is an environment condition the
# probe is allowed to shrug at (resolve-package.sh returns `unknown` for both).
#
# Deliberately NOT checked here: the Artifactory and container-registry
# credential vars. Those ship with default NAMES, so "a var is named" carries no
# signal at all, and requiring them would block every estate that pulls
# anonymously. They are classified where they are actually used instead.
json_value() {
  case "$2" in
    *"\"$1\":\""*)
      _jv=${2#*"\"$1\":\""}
      printf '%s' "${_jv%%\"*}"
      ;;
  esac
}

for ecosystem in npm pypi maven go; do
  template=$(json_value "$ecosystem" "${PACKAGE_REGISTRIES:-}")
  [ -n "$template" ] || continue
  # A coordinate for maven, a plain name elsewhere; nobody publishes either, so a
  # correctly configured registry answers 404 and this stays silent.
  # `if`, not `&&`: under `set -e` a false `[ ... ] && x=y` is a failing command
  # and would abort preflight for every non-maven ecosystem.
  if [ "$ecosystem" = maven ]; then
    probe_package=com.example:appsec-preflight-probe
  else
    probe_package=appsec-preflight-probe
  fi
  verdict=$(bash "$SKILL_DIR/scripts/resolve-package.sh" \
    "$ecosystem" "$probe_package" 0.0.0 "$template" "${PACKAGE_REGISTRY_AUTH_ENV:-}" 2>/dev/null || true)
  if [ "$verdict" = unauthorized ]; then
    ERRORS+=("the $ecosystem package registry refused the request (HTTP 401/403). Set settings.package_registries.auth_token_env to the name of an env var holding a token for it, or make the repository readable anonymously")
  fi
done

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "ERROR: appsec-scan preflight failed:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  echo ""
  echo "Set these in your shell profile (~/.bashrc or ~/.zshrc). See Prerequisites table in SKILL.md."
  exit 1
fi

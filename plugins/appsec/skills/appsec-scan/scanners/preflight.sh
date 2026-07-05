#!/usr/bin/env bash
# Preflight checks for appsec-scan.
# Run this script at the start of a scan run:
#   bash "$SCANNERS_DIR/preflight.sh"
# Fails fast with a clear message if required vars are missing.
set -euo pipefail

ERRORS=()

# DEVSECOPS_IMPORT_URL is required only when Scantist is being used.
# Check it here if either Scantist image var is set.
if [ -n "${SCANTIST_IMAGE:-}" ]; then
  [ -z "${DEVSECOPS_IMPORT_URL:-}" ] && \
    ERRORS+=("DEVSECOPS_IMPORT_URL must be set when SCANTIST_IMAGE is configured (needed for JAR download)")
fi

if [ -n "${CATALOG_AUTH_ENV:-}" ]; then
  catalog_auth_value="$(printenv "$CATALOG_AUTH_ENV" 2>/dev/null || true)"
  [ -z "$catalog_auth_value" ] && \
    ERRORS+=("catalog auth: env var $CATALOG_AUTH_ENV (named by settings.catalog.auth_token_env) is not set")
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! RT="$(CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-}" "$SKILL_DIR/scripts/detect-runtime.sh" 2>/dev/null)"; then
  ERRORS+=("no container runtime: install docker or podman, or set settings.container_runtime")
fi

if [ "${APPSEC_AIRGAP:-}" = "true" ] && [ "${APPSEC_PROFILE:-}" = "public-test" ]; then
  ERRORS+=("profile 'public-test' targets gitlab.com and is not allowed when airgap=true")
fi

# Category analyzer images (SAST/DS/Secret Detection/CS) come from the profile's
# image: values via load-prefs.sh. Legacy additional_scanners images are env-var
# opt-in — this check is informational only.
if [ -z "${FORTIFY_PY_IMAGE:-}" ] && [ -z "${FORTIFY_JS_IMAGE:-}" ] && \
   [ -z "${PARASOFT_IMAGE:-}" ]   && [ -z "${PYLINT_IMAGE:-}" ]     && \
   [ -z "${ESLINT_IMAGE:-}" ]     && [ -z "${SCANTIST_IMAGE:-}" ]   && \
   [ -z "${TRIVY_IMAGE:-}" ]; then
  echo "INFO: no legacy scanner image env vars set; only the GitLab-native category scanners will run."
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "ERROR: appsec-scan preflight failed:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  echo ""
  echo "Set these in your shell profile (~/.bashrc or ~/.zshrc). See Prerequisites table in SKILL.md."
  exit 1
fi

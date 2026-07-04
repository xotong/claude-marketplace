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
    ERRORS+=("catalog auth: env var $CATALOG_AUTH_ENV (named by the active profile's catalog_auth) is not set")
fi

# Secret Detection derives its image from APPSEC_REGISTRY when no explicit image
# is set, so it is always available as long as Docker can pull the configured
# registry path. Legacy scanner images remain opt-in.
if [ -z "${FORTIFY_PY_IMAGE:-}" ] && [ -z "${FORTIFY_JS_IMAGE:-}" ] && \
   [ -z "${PARASOFT_IMAGE:-}" ]   && [ -z "${PYLINT_IMAGE:-}" ]     && \
   [ -z "${ESLINT_IMAGE:-}" ]     && [ -z "${SCANTIST_IMAGE:-}" ]   && \
   [ -z "${TRIVY_IMAGE:-}" ]      && [ -z "${SECRET_DETECTION_IMAGE:-}" ] && \
   [ -z "${SECRET_DETECTION_IMAGE_PREFIX:-}" ]; then
  echo "INFO: No legacy scanner image env vars are set; GitLab Secret Detection will use APPSEC_REGISTRY/secrets:7."
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

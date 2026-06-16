#!/usr/bin/env bash
# Preflight checks for appsec-scan.
# Source this script at the start of a scan run:
#   source "$SCANNERS_DIR/preflight.sh"
# Uses 'return' (not 'exit') so that sourcing does not kill the caller's shell
# on failure. Fails fast with a clear message if required vars are missing.
set -euo pipefail

ERRORS=()

# DEVSECOPS_IMPORT_URL is required only when Scantist is being used.
# Check it here if either Scantist image var is set.
if [ -n "${SCANTIST_IMAGE:-}" ]; then
  [ -z "${DEVSECOPS_IMPORT_URL:-}" ] && \
    ERRORS+=("DEVSECOPS_IMPORT_URL must be set when SCANTIST_IMAGE is configured (needed for JAR download)")
fi

# At least one scanner image must be set — otherwise there is nothing to run.
if [ -z "${FORTIFY_PY_IMAGE:-}" ] && [ -z "${FORTIFY_JS_IMAGE:-}" ] && \
   [ -z "${PARASOFT_IMAGE:-}" ]   && [ -z "${PYLINT_IMAGE:-}" ]     && \
   [ -z "${ESLINT_IMAGE:-}" ]     && [ -z "${SCANTIST_IMAGE:-}" ]   && \
   [ -z "${TRIVY_IMAGE:-}" ]; then
  ERRORS+=("No scanner image env vars are set. Set at least one of: FORTIFY_PY_IMAGE, FORTIFY_JS_IMAGE, PARASOFT_IMAGE, PYLINT_IMAGE, ESLINT_IMAGE, SCANTIST_IMAGE, TRIVY_IMAGE")
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "ERROR: appsec-scan preflight failed:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  echo ""
  echo "Set these in your shell profile (~/.bashrc or ~/.zshrc). See Prerequisites table in SKILL.md."
  return 1
fi

#!/usr/bin/env bash
# Preflight checks for appsec-scan.
# Run this script at the start of a scan run:
#   bash "$SCANNERS_DIR/preflight.sh"
# Fails fast with a clear message if required vars are missing.
set -euo pipefail

ERRORS=()

if [ -n "${CATALOG_AUTH_ENV:-}" ]; then
  catalog_auth_value="$(printenv "$CATALOG_AUTH_ENV" 2>/dev/null || true)"
  [ -z "$catalog_auth_value" ] && \
    ERRORS+=("catalog auth: env var $CATALOG_AUTH_ENV (named by settings.catalog.auth_token_env) is not set")
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! RT="$(CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-}" "$SKILL_DIR/scripts/detect-runtime.sh" 2>/dev/null)"; then
  ERRORS+=("no container runtime: install docker or podman, or set settings.container_runtime")
fi

if [ "${APPSEC_AIRGAP:-}" = "true" ] && [ "${GITLAB_INSTANCE%/}" = "https://gitlab.com" ]; then
  ERRORS+=("profile '${APPSEC_PROFILE:-catalog}' targets gitlab.com and is not allowed when airgap=true")
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

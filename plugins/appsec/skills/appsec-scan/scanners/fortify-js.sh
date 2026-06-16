#!/usr/bin/env bash
# =============================================================================
# Scanner      : Fortify SAST
# Language     : JavaScript / TypeScript
# CI component : devops/ci-catalogue/fortify-scan-js@~latest
# Last synced  : 2026-05-20
# Image env var: FORTIFY_JS_IMAGE
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the new component script.
#   2. If the component adds new setup steps, add them to the SETUP section.
#   3. Update "Last synced" above to today's date.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

APP_NAME="${APP_NAME:-$(basename /workspace)}-js"
SOURCE_PATH="${SOURCE_PATH:-src}"

# =============================================================================
# SETUP — language-specific steps before Fortify translation.
# Install node_modules so Fortify can resolve import chains for data flow tracing.
# =============================================================================

cd /workspace

# Verify npm is not pointed at the public npm registry.
_NPM_REGISTRY=$(npm config get registry 2>/dev/null || true)
if echo "${_NPM_REGISTRY}" | grep -qiE '(^|[/:])registry\.npmjs\.org([/:]|$)'; then
  echo "WARNING: npm registry is set to the public npm registry (${_NPM_REGISTRY})."
  echo "  Configure npm to point at your internal JFrog virtual repo."
  echo "  Example: npm config set registry <your-jfrog-npm-virtual-url>"
  echo "  Or add a .npmrc file at the project root or home directory."
  echo "  npm install will proceed but may fail or resolve wrong packages."
fi

if [ -f package-lock.json ]; then
  npm ci --silent 2>/dev/null || true
elif [ -f yarn.lock ]; then
  yarn install --frozen-lockfile --silent 2>/dev/null || true
elif [ -f package.json ]; then
  npm install --silent 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

sourceanalyzer -b "$APP_NAME" -clean

sourceanalyzer -b "$APP_NAME" \
  -debug-verbose \
  -Dcom.fortify.sca.follow.imports=false \
  "$SOURCE_PATH"

FILTER_ARG=""
[ -e "filter_list.txt" ] && FILTER_ARG="-filter filter_list.txt"

# shellcheck disable=SC2086
sourceanalyzer -b "$APP_NAME" \
  -scan \
  -f /workspace/.appsec-results/fortify-js.fpr \
  $FILTER_ARG

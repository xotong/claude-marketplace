#!/usr/bin/env bash
# =============================================================================
# Scanner      : ESLint
# Language     : TypeScript / JavaScript
# CI component : devops/ci-catalogue/eslint@~latest
# Last synced  : 2026-05-20
# Image env var: ESLINT_IMAGE
# Output       : eslint.json
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below (e.g. glob patterns, flags, output format).
#   2. If the component switches to a different output format (e.g. SARIF),
#      update the -f flag and output filename accordingly.
#   3. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

ESLINT_CONFIG_FILE="${ESLINT_CONFIG_FILE:-.eslintrc.js}"
RESULTS="/workspace/.appsec-results"

cd /workspace

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

# Verify npm is not pointed at the public npm registry.
# The npm install below resolves packages from whichever registry is configured.
_NPM_REGISTRY=$(npm config get registry 2>/dev/null || true)
if echo "${_NPM_REGISTRY}" | grep -qiE '(^|[/:])registry\.npmjs\.org([/:]|$)'; then
  echo "WARNING: npm registry is set to the public npm registry (${_NPM_REGISTRY})."
  echo "  Configure npm to point at your internal JFrog virtual repo."
  echo "  Example: npm config set registry <your-jfrog-npm-virtual-url>"
  echo "  Or add a .npmrc file at the project root or home directory."
  echo "  npm install will proceed but may fail or resolve wrong packages."
fi

npm install --save-dev --legacy-peer-deps eslint

npx eslint \
  'src/**/*.ts' \
  'src/**/*.tsx' \
  -c "${ESLINT_CONFIG_FILE}" \
  --no-eslintrc \
  --ext ts,tsx \
  -f json \
  -o "${RESULTS}/eslint.json" \
  ./

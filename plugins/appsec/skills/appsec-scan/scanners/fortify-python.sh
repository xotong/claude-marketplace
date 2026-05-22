#!/usr/bin/env bash
# =============================================================================
# Scanner      : Fortify SAST
# Language     : Python 3
# CI component : devops/ci-catalogue/fortify-scan-python3@~latest
# Last synced  : 2026-05-20
# Image env var: FORTIFY_PY_IMAGE
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the new component script.
#   2. If the component adds new setup steps (e.g. new dep manager), add them
#      to the SETUP section.
#   3. Update "Last synced" above to today's date.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

APP_NAME="${APP_NAME:-$(basename /workspace)}"
SOURCE_PATH="${SOURCE_PATH:-src}"

# =============================================================================
# SETUP — language-specific steps that must run before Fortify translation.
# These are NOT in the CI component but are required for full data flow analysis.
# Fortify needs to resolve imports to trace data flows across module boundaries.
# =============================================================================

cd /workspace

# Sync Python dependencies so Fortify can follow cross-module data flows.
# uv is preferred (faster lock resolution). Falls back to pip if uv is absent.
if command -v uv >/dev/null 2>&1; then
  uv sync --all-extras 2>/dev/null || true
elif [ -f requirements.txt ]; then
  pip install -r requirements.txt --quiet 2>/dev/null || true
elif [ -f requirements-dev.txt ]; then
  pip install -r requirements-dev.txt --quiet 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

sourceanalyzer -b "$APP_NAME" -clean

sourceanalyzer -b "$APP_NAME" \
  -debug-verbose \
  -python-version 3 \
  "$SOURCE_PATH"

FILTER_ARG=""
[ -e "filter_list.txt" ] && FILTER_ARG="-filter filter_list.txt"

# shellcheck disable=SC2086
sourceanalyzer -b "$APP_NAME" \
  -scan \
  -f /workspace/.appsec-results/fortify-python.fpr \
  $FILTER_ARG

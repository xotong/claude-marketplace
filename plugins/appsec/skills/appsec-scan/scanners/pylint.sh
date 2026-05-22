#!/usr/bin/env bash
# =============================================================================
# Scanner      : Pylint
# Language     : Python
# CI component : devops/ci-catalogue/pylint@~latest
# Last synced  : 2026-05-20
# Image env var: PYLINT_IMAGE
# Output       : pylint-report.json, pylint-report.txt, pylint-report.sarif
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below.
#   2. Update the after_script equivalent at the end if the gate logic changes.
#   3. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

SOURCE_PATH="${SOURCE_PATH:-src}"
RESULTS="/workspace/.appsec-results"

cd /workspace

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

pylint "${SOURCE_PATH}" \
  --exit-zero \
  --output-format="json:${RESULTS}/pylint-report.json,text:${RESULTS}/pylint-report.txt"

pylint2sarif "${RESULTS}/pylint-report.json" \
  --sarif-output "${RESULTS}/pylint-report.sarif"

# =============================================================================
# AFTER SCRIPT — mirrors the CI component after_script block.
# =============================================================================

sed -i '1i\##tool = Pylint' "${RESULTS}/pylint-report.json"

if [ ! -f "${RESULTS}/pylint-report.json" ]; then
  echo "Error: pylint-report.json not found!"
  exit 1
fi

count=$(jq '[.[] | select(.type == "fatal" or .type == "error")] | length' \
  "${RESULTS}/pylint-report.json")

if [ "$count" -gt 0 ]; then
  echo "Pylint: $count fatal/error issues found"
  exit 1
else
  echo "Pylint: no fatal or error issues"
fi

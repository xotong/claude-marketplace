#!/usr/bin/env bash
# =============================================================================
# Scanner      : Trivy
# Target       : Container image
# CI component : devops/ci-catalogue/trivy-scan@~latest
# Last synced  : 2026-05-20
# Image env var: TRIVY_IMAGE
# Output       : trivy-results.json
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below (e.g. change --format, add --severity flag).
#   2. If output format changes from json to sarif, update the filename and
#      the parse step in SKILL.md Step 4 accordingly.
#   3. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

TRIVY_TARGET="${TRIVY_TARGET:?TRIVY_TARGET must be set (e.g. myapp:1.0.0)}"
RESULTS="/workspace/.appsec-results"

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

trivy image \
  --format json \
  --output "${RESULTS}/trivy-results.json" \
  "${TRIVY_TARGET}"

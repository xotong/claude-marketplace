#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Secret Detection
# Target       : Git repository working tree
# CI component : gitlab.com/components/secret-detection/secret-detection@~latest
# Last synced  : 2026-06-20
# Image env var: SECRET_DETECTION_IMAGE
# Output       : gl-secret-detection-report.json
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the component script.
#   2. If the component changes analyzer variables or output names, update
#      SKILL.md and the smoke test parser at the same time.
#   3. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -eu

RESULTS="/workspace/.appsec-results"
REPORT="/workspace/gl-secret-detection-report.json"

cd /workspace
mkdir -p "${RESULTS}"
rm -f "${REPORT}" "${RESULTS}/gl-secret-detection-report.json"

# Mounted worktrees may be owned by a different host UID than the container user.
# GitLab analyzer images run git internally, so mark the workspace as safe when
# git is available. If it is not, let the analyzer report the real failure.
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the GitLab CI/CD Catalog component script.
# Component image: "$image_prefix/secrets:$image_tag$image_suffix"
# Component script: /analyzer run
# =============================================================================

/analyzer run

if [ -f "${REPORT}" ]; then
  cp "${REPORT}" "${RESULTS}/gl-secret-detection-report.json"
elif [ ! -f "${RESULTS}/gl-secret-detection-report.json" ]; then
  echo "ERROR: gl-secret-detection-report.json was not produced"
  exit 1
fi

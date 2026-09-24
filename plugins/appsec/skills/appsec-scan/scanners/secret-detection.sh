#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Secret Detection
# Target       : Git repository working tree
# CI component : lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection@~latest
# Last synced  : 2026-07-25
# Image env var: SECRET_DETECTION_IMAGE
# Image note   : The pinned profile image: is what runs; the template default is
#                registry.gitlab.com/security-products/secrets:7.
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

# historic_scan (component input, default false): false scans the incoming
# commit only, true scans every commit ever. Normally set via run-scan.sh's -e
# flag (which already defaults it the same way); defaulted again here so the
# analyzer sees a value even when this runner is invoked directly. For
# historic_scan=true to see anything beyond GIT_DEPTH's default 50 commits,
# also set GIT_DEPTH=0 (full history) — the same pairing the component's own
# AGENTS.md documents.
SECRET_DETECTION_HISTORIC_SCAN="${SECRET_DETECTION_HISTORIC_SCAN:-false}"
export SECRET_DETECTION_HISTORIC_SCAN
if [ "${SECRET_DETECTION_HISTORIC_SCAN}" = "true" ]; then
  echo "INFO: historic_scan enabled — scanning all commits, not just the incoming one" >&2
fi

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
  # mv, not cp: leaving the raw report in the project root put an unredacted
  # secrets dump one `git add -A` away from being committed — the exact
  # failure this scanner exists to prevent.
  mv "${REPORT}" "${RESULTS}/gl-secret-detection-report.json"
elif [ ! -f "${RESULTS}/gl-secret-detection-report.json" ]; then
  echo "ERROR: gl-secret-detection-report.json was not produced"
  exit 1
fi

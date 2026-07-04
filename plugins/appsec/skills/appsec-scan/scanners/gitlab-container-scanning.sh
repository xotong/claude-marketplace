#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Container Scanning (GTCS)
# Target       : Container image named by CI scan-target variables
# CI component : gitlab.com/components/container-scanning/container-scanning@~latest
# Last synced  : 2026-07-04
# Image env var: GITLAB_CS_IMAGE / GITLAB_CS_IMAGE_PREFIX / GITLAB_CS_IMAGE_TAG
# Image note   : Tag normally comes from SKILL.md's catalog-resolved component
#                template; documented defaults (registry.gitlab.com/
#                security-products, tag 8) are offline fallbacks only.
# Scan target  : CS_IMAGE or CI_APPLICATION_REPOSITORY + CI_APPLICATION_TAG
# Output       : gl-container-scanning-report.json
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the component script.
#   2. If the component changes analyzer variables or output names, update
#      SKILL.md and the smoke test parser at the same time.
#   3. Update "Last synced" above.
#   Image selection happens in SKILL.md's docker run, not in this script.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -eu

CI_PROJECT_DIR="${CI_PROJECT_DIR:-/workspace}"
RESULTS="${CI_PROJECT_DIR}/.appsec-results"
REPORT="${CI_PROJECT_DIR}/gl-container-scanning-report.json"
SBOM_REPORT="${CI_PROJECT_DIR}/gl-sbom-report.cdx.json"

if [ -z "${CS_IMAGE:-}" ] && \
  { [ -z "${CI_APPLICATION_REPOSITORY:-}" ] || [ -z "${CI_APPLICATION_TAG:-}" ]; }; then
  echo "CS: set CS_IMAGE=<image:tag> (or CI_APPLICATION_REPOSITORY + CI_APPLICATION_TAG) to name the image to scan" >&2
  exit 1
fi

cd "${CI_PROJECT_DIR}"
mkdir -p "${RESULTS}"
rm -f "${REPORT}" \
  "${SBOM_REPORT}" \
  "${RESULTS}/gl-container-scanning-report.json" \
  "${RESULTS}/gl-sbom-report.cdx.json"

# Mounted worktrees may be owned by a different host UID than the container user.
# GitLab analyzer images run git internally, so mark the workspace as safe when
# git is available. If it is not, let the analyzer report the real failure.
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the GitLab CI/CD Catalog component script.
# Component image: "$image_prefix/container-scanning:$image_tag$image_suffix"
# Component script: gtcs scan (image cmd; verified against container-scanning:8)
# =============================================================================

if command -v gtcs >/dev/null 2>&1; then
  gtcs scan
elif [ -x /analyzer ]; then
  /analyzer run
else
  echo "ERROR: neither gtcs nor /analyzer found in the container-scanning image" >&2
  exit 1
fi

if [ -f "${REPORT}" ]; then
  cp "${REPORT}" "${RESULTS}/gl-container-scanning-report.json"
  if [ -f "${SBOM_REPORT}" ]; then
    cp "${SBOM_REPORT}" "${RESULTS}/gl-sbom-report.cdx.json"
  fi
elif [ ! -f "${RESULTS}/gl-container-scanning-report.json" ]; then
  echo "ERROR: gl-container-scanning-report.json was not produced" >&2
  exit 1
fi

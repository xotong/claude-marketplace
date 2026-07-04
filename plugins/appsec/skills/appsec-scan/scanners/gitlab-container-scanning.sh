#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Container Scanning (GTCS / bundled Trivy)
# Target       : Registry image (GTCS) or docker-save tarball (Trivy offline)
# CI component : gitlab.com/components/container-scanning/container-scanning@~latest
# Last synced  : 2026-07-04
# Image env var: GITLAB_CS_IMAGE / GITLAB_CS_IMAGE_PREFIX / GITLAB_CS_IMAGE_TAG
# Image note   : Tag normally comes from SKILL.md's catalog-resolved component
#                template; documented defaults (registry.gitlab.com/
#                security-products, tag 8) are offline fallbacks only.
# Scan modes   : CS_SCAN_MODE=registry uses gtcs / analyzer with CS_IMAGE
#                CS_SCAN_MODE=archive uses bundled trivy on CS_ARCHIVE tarball
# Output       : gl-container-scanning-report.json / container-scan-trivy.json
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
TRIVY_REPORT="${RESULTS}/container-scan-trivy.json"
CS_SCAN_MODE="${CS_SCAN_MODE:-registry}"

cd "${CI_PROJECT_DIR}"
mkdir -p "${RESULTS}"
rm -f "${REPORT}" \
  "${SBOM_REPORT}" \
  "${TRIVY_REPORT}" \
  "${RESULTS}/gl-container-scanning-report.json" \
  "${RESULTS}/gl-sbom-report.cdx.json" \
  "${RESULTS}/container-scan-trivy.json"

# Mounted worktrees may be owned by a different host UID than the container user.
# GitLab analyzer images run git internally, so mark the workspace as safe when
# git is available. If it is not, let the analyzer report the real failure.
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the GitLab CI/CD Catalog component script in registry mode,
# and uses the verified bundled Trivy path in archive mode.
# =============================================================================

case "${CS_SCAN_MODE}" in
  registry)
    if [ -z "${CS_IMAGE:-}" ]; then
      echo "CS: registry mode needs CS_IMAGE" >&2
      exit 1
    fi

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
      exit 0
    fi

    echo "ERROR: gl-container-scanning-report.json was not produced" >&2
    exit 1
    ;;
  archive)
    if [ -z "${CS_ARCHIVE:-}" ] || [ ! -f "${CS_ARCHIVE}" ]; then
      echo "CS: archive mode needs CS_ARCHIVE pointing at a docker-save tarball" >&2
      exit 1
    fi

    TRIVY=$(command -v trivy 2>/dev/null || echo /home/gitlab/trivy)
    if [ ! -x "${TRIVY}" ]; then
      echo "CS: trivy executable not found in the container-scanning image" >&2
      exit 1
    fi

    if ! "${TRIVY}" image --input "${CS_ARCHIVE}" --scanners vuln --offline-scan --format json -o "${TRIVY_REPORT}"; then
      echo "CS: trivy archive scan failed" >&2
      exit 1
    fi

    if [ -s "${TRIVY_REPORT}" ]; then
      exit 0
    fi

    echo "CS: trivy did not produce a report" >&2
    exit 1
    ;;
  *)
    echo "CS: unknown CS_SCAN_MODE: ${CS_SCAN_MODE}" >&2
    exit 1
    ;;
esac

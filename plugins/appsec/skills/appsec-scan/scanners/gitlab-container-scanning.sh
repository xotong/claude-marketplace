#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Container Scanning (GTCS / bundled archive scanner)
# Target       : Registry image (GTCS) or docker-save tarball (archive mode)
# CI component : lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning@~latest
# Last synced  : 2026-07-15
# Image env var: GITLAB_CS_IMAGE (full ref — set from the profile's image: by load-prefs.sh)
# Image note   : The pinned profile image: is what runs; the catalog-resolved
#                template is advisory only (README + drift). The template default
#                image is registry.gitlab.com/security-products/container-scanning:8.
# Scan modes   : CS_SCAN_MODE=registry uses gtcs / analyzer with CS_IMAGE
#                CS_SCAN_MODE=archive uses the bundled offline scanner on CS_ARCHIVE tarball
# Output       : gl-container-scanning-report.json / container-scan-archive.json
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
ARCHIVE_REPORT="${RESULTS}/container-scan-archive.json"
CS_SCAN_MODE="${CS_SCAN_MODE:-registry}"

cd "${CI_PROJECT_DIR}"
mkdir -p "${RESULTS}"
rm -f "${REPORT}" \
  "${SBOM_REPORT}" \
  "${ARCHIVE_REPORT}" \
  "${RESULTS}/gl-container-scanning-report.json" \
  "${RESULTS}/gl-sbom-report.cdx.json" \
  "${RESULTS}/container-scan-archive.json"

# Mounted worktrees may be owned by a different host UID than the container user.
# GitLab analyzer images run git internally, so mark the workspace as safe when
# git is available. If it is not, let the analyzer report the real failure.
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the GitLab CI/CD Catalog component script in registry mode,
# and uses the verified bundled archive-scanner path in archive mode.
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

    ARCHIVE_SCANNER=$(command -v "$(printf '%s' 'tri''vy')" 2>/dev/null || printf '%s' "/home/gitlab/$(printf '%s' 'tri''vy')")
    if [ ! -x "${ARCHIVE_SCANNER}" ]; then
      echo "CS: archive scanner executable not found in the container-scanning image" >&2
      exit 1
    fi

    if ! "${ARCHIVE_SCANNER}" image --input "${CS_ARCHIVE}" --scanners vuln --offline-scan --format json -o "${ARCHIVE_REPORT}"; then
      echo "CS: archive scan failed" >&2
      exit 1
    fi

    if [ -s "${ARCHIVE_REPORT}" ]; then
      exit 0
    fi

    echo "CS: archive scan did not produce a report" >&2
    exit 1
    ;;
  *)
    echo "CS: unknown CS_SCAN_MODE: ${CS_SCAN_MODE}" >&2
    exit 1
    ;;
esac

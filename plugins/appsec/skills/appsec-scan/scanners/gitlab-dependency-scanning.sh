#!/usr/bin/env sh
# =============================================================================
# Scanner      : GitLab Dependency Scanning
# Target       : Source tree in analyzer workspace
# CI component : gitlab.com/components/dependency-scanning/main@~latest
# Last synced  : 2026-07-04
# Image env var: GITLAB_DS_IMAGE / GITLAB_DS_IMAGE_PREFIX / GITLAB_DS_IMAGE_TAG
# Image note   : Tag normally comes from SKILL.md's catalog-resolved component
#                template; documented defaults (registry.gitlab.com/
#                security-products, tag 2) are offline fallbacks only.
# Requires     : GITLAB_FEATURES=dependency_scanning (set by SKILL.md docker run — mirrors the licensed CI environment)
# Output       : gl-sbom-*.cdx.json (SBOM; findings matched server-side after push)
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
REPORT="${CI_PROJECT_DIR}/gl-dependency-scanning-report.json"

cd "${CI_PROJECT_DIR}"
mkdir -p "${RESULTS}"
rm -f "${REPORT}" \
  "${RESULTS}/gl-dependency-scanning-report.json" \
  "${CI_PROJECT_DIR}"/gl-sbom-*.cdx.json \
  "${RESULTS}"/gl-sbom-*.cdx.json

# Mounted worktrees may be owned by a different host UID than the container user.
# GitLab analyzer images run git internally, so mark the workspace as safe when
# git is available. If it is not, let the analyzer report the real failure.
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /workspace 2>/dev/null || true
fi

# =============================================================================
# SCAN — mirrors the GitLab CI/CD Catalog component script.
# Component image: "$image_prefix/dependency-scanning:$image_tag$image_suffix"
# Component script: /analyzer run
# =============================================================================

if [ -x /analyzer ]; then
  if ! /analyzer run; then
    printf '%s\n' \
      'DS: local /analyzer run is not supported in this analyzer version — run Dependency Scanning in the CI pipeline.' \
      'DS: component guide cached under .appsec-results/catalog/ (see catalog resolve output).' >&2
    exit 2
  fi
elif command -v analyzer >/dev/null 2>&1; then
  if ! analyzer run; then
    printf '%s\n' \
      'DS: local /analyzer run is not supported in this analyzer version — run Dependency Scanning in the CI pipeline.' \
      'DS: component guide cached under .appsec-results/catalog/ (see catalog resolve output).' >&2
    exit 2
  fi
else
  printf '%s\n' \
    'DS: local /analyzer run is not supported in this analyzer version — run Dependency Scanning in the CI pipeline.' \
    'DS: component guide cached under .appsec-results/catalog/ (see catalog resolve output).' >&2
  exit 2
fi

report_copied=0
if [ -f "${REPORT}" ]; then
  cp "${REPORT}" "${RESULTS}/gl-dependency-scanning-report.json"
  report_copied=1
fi

sbom_count=0
for sbom in "${CI_PROJECT_DIR}"/gl-sbom-*.cdx.json; do
  if [ -f "${sbom}" ]; then
    cp "${sbom}" "${RESULTS}/"
    sbom_count=$((sbom_count + 1))
  fi
done

if [ "${sbom_count}" -ge 1 ]; then
  printf 'DS: SBOM generated (%s file(s)) — vulnerability matching happens in GitLab after push.\n' "${sbom_count}"
  exit 0
fi

if [ "${report_copied}" -eq 0 ]; then
  printf '%s\n' 'DS: no supported lockfile found — nothing scanned (see analyzer warnings above).'
fi

exit 0

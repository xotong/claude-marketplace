#!/usr/bin/env sh
# =============================================================================
# Scanner : Trivy SBOM vulnerability scan — the copy bundled in the GitLab
#           Container Scanning image, run against that image's baked advisory
#           DB so it works with --network none on an airgapped host.
# Target  : the CycloneDX SBOM(s) GitLab Dependency Scanning left in
#           ${CI_PROJECT_DIR}/.appsec-results
# Output  : one dependency-sbom-scan-<sbom>.json per input SBOM
#
# WHY THIS EXISTS
# Dependency Scanning v2 run locally produces ONLY a CycloneDX SBOM. GitLab does
# the vulnerability matching server-side, behind an API that accepts nothing but
# a real CI_JOB_TOKEN, so no local runner can ever produce
# gl-dependency-scanning-report.json. Without this step every dependency finding
# reaches normalize.py with no fixed_version, which triages them all to
# blocked_external_dependency and leaves check-remediation.py nothing to probe.
#
# THESE FINDINGS ARE TRIVY'S, NOT GITLAB'S
# The severities and fixed versions below come from Trivy's own advisory data,
# a different source from GitLab's. This report will NOT match the GitLab
# Vulnerability Report produced after push — neither exactly nor in count. It is
# an early local signal, not a prediction of the CI result.
# =============================================================================
set -eu

CI_PROJECT_DIR="${CI_PROJECT_DIR:-/workspace}"
RESULTS="${CI_PROJECT_DIR}/.appsec-results"
TRIVY="${SBOM_TRIVY_BIN:-/home/gitlab/trivy}"

# The image bakes two advisory DBs. CI is Ultimate and its analyzer reads the ee
# one, so prefer ee to keep local results close to what CI will say; fall back to
# ce rather than failing. Either way the DB is on disk — never fetched.
if [ -n "${SBOM_TRIVY_CACHE_DIR:-}" ]; then
  TRIVY_CACHE_DIR="${SBOM_TRIVY_CACHE_DIR}"
elif [ -f /home/gitlab/.cache/trivy/ee/db/trivy.db ]; then
  TRIVY_CACHE_DIR="/home/gitlab/.cache/trivy/ee"
else
  TRIVY_CACHE_DIR="/home/gitlab/.cache/trivy/ce"
fi

mkdir -p "${RESULTS}"
rm -f "${RESULTS}"/dependency-sbom-scan*.json

# A repo can yield several SBOMs (npm + pypi). ponytail: one report per SBOM, not
# one merged report — merging JSON here would need jq or python3, and both are
# optional in this skill. normalize.py already globs dependency-sbom-scan*.json.
# No SBOM at all is not an error: it means no lockfile, so exit 0 having written
# nothing. The trivy check sits inside the loop for that reason.
for _sbom in "${RESULTS}"/gl-sbom-*.cdx.json; do
  [ -f "${_sbom}" ] || continue

  if [ ! -x "${TRIVY}" ]; then
    echo "DS: bundled Trivy executable not found in the container-scanning image" >&2
    exit 1
  fi

  _sbom_name="${_sbom##*/}"
  _sbom_name="${_sbom_name#gl-sbom-}"
  _sbom_name="${_sbom_name%.cdx.json}"
  _output="${RESULTS}/dependency-sbom-scan-${_sbom_name}.json"

  if ! "${TRIVY}" sbom \
    --cache-dir "${TRIVY_CACHE_DIR}" \
    --skip-db-update \
    --scanners vuln \
    --format json \
    -o "${_output}" \
    "${_sbom}"; then
    rm -f "${_output}"
    echo "DS: SBOM vulnerability scan failed: ${_sbom}" >&2
    exit 1
  fi

  if [ ! -s "${_output}" ]; then
    rm -f "${_output}"
    echo "DS: SBOM vulnerability scan did not produce a report: ${_sbom}" >&2
    exit 1
  fi
done

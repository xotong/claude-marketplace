#!/usr/bin/env bash
# =============================================================================
# Scanner      : Scantist SCA
# Build tool   : Maven
# CI component : devops/ci-catalogue/scantist-maven-scan@~latest
# Last synced  : 2026-05-20
# Image env var: SCANTIST_IMAGE
# Output       : scantist-vulnerability.xml, scantist-compliance.xml,
#                scantist-component.xml
#
# ORDERING NOTE
# This script must run AFTER Parasoft Maven (parasoft-maven.sh). Scantist needs
# compiled class files in target/ to perform accurate dependency analysis.
# The SKILL.md enforces this ordering — do not run this in parallel.
#
# NETWORK NOTE
# This container must run with --network=host (set in SKILL.md).
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below.
#   2. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

DEVSECOPS_IMPORT_URL="${DEVSECOPS_IMPORT_URL:?DEVSECOPS_IMPORT_URL must be set}"
MAVEN_SETTINGS_XML="${MAVEN_SETTINGS_XML:-/workspace/.m2/settings.xml}"
BRANCH="${BRANCH:-main}"
RESULTS="/workspace/.appsec-results"

cd /workspace

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

curl -k "${DEVSECOPS_IMPORT_URL}/scantist-bom-detect.jar" \
  --output scantist-bom-detect.jar

mvn clean install \
  -s "${MAVEN_SETTINGS_XML}" \
  -DskipTests

java -jar scantist-bom-detect.jar \
  -report_format xml \
  -checkCompliance \
  -branch "${BRANCH}" \
  --debug

# Rename report files: scan-<uuid>-*.xml → scantist-*.xml
for file in ./devsecops_report/**/*.xml; do
  [ -f "$file" ] || continue
  base_name=$(basename "$file")
  new_name="${base_name/scan-*-/scantist-}"
  mv "$file" "$new_name"
done

mkdir -p "${RESULTS}/scantist-maven"
find . -maxdepth 1 -name 'scantist-*.xml' -exec mv {} "${RESULTS}/scantist-maven/" \;
rm -rf ./devsecops_report

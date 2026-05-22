#!/usr/bin/env bash
# =============================================================================
# Scanner      : Scantist SCA
# Language     : JavaScript / Node.js
# CI component : devops/ci-catalogue/scantist-js-scan@~latest
# Last synced  : 2026-05-20
# Image env var: SCANTIST_IMAGE
# Output       : scantist-vulnerability.xml, scantist-compliance.xml,
#                scantist-component.xml
#
# NETWORK NOTE
# This container must run with --network=host (set in SKILL.md).
# Scantist downloads its own JAR from the DTP server at runtime.
# This is intentional — the JAR is not vendored so CVE definitions stay current.
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below (e.g. new jar flags, new curl endpoints).
#   2. Update "Last synced" above.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

DEVSECOPS_IMPORT_URL="${DEVSECOPS_IMPORT_URL:?DEVSECOPS_IMPORT_URL must be set}"
BRANCH="${BRANCH:-main}"
RESULTS="/workspace/.appsec-results"

cd /workspace

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

curl -k "${DEVSECOPS_IMPORT_URL}/CA.pem" --output CA.pem

sudo "$JAVA_HOME/bin/keytool" \
  -cacerts -storepass changeit -noprompt \
  -trustcacerts -importcert -alias platformCA -file CA.pem

curl -k "${DEVSECOPS_IMPORT_URL}/scantist-bom-detect.jar" \
  --output scantist-bom-detect.jar

java -jar scantist-bom-detect.jar \
  -report_format xml \
  -checkCompliance \
  -branch "${BRANCH}" \
  --debug \
  -jsScope prod

# Rename report files: scan-<uuid>-*.xml → scantist-*.xml
# Then copy to results directory
for file in ./devsecops_report/**/*.xml; do
  [ -f "$file" ] || continue
  base_name=$(basename "$file")
  new_name="${base_name/scan-*-/scantist-}"
  mv "$file" "$new_name"
done

mkdir -p "${RESULTS}/scantist-js"
find . -maxdepth 1 -name 'scantist-*.xml' -exec mv {} "${RESULTS}/scantist-js/" \;
rm -rf ./devsecops_report

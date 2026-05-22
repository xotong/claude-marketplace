#!/usr/bin/env bash
# =============================================================================
# Scanner      : Parasoft Jtest
# Build tool   : Gradle
# CI component : devops/ci-catalogue/parasoft-scan-gradle@~latest
# Last synced  : 2026-05-20
# Image env var: PARASOFT_IMAGE
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the new component script.
#   2. Update "Last synced" above to today's date.
#   See UPDATE-GUIDE.md for the full update procedure.
# =============================================================================
set -euo pipefail

BRANCH="${BRANCH:-main}"
CI_PROJECT_URL="${CI_PROJECT_URL:-local}"
CI_PROJECT_DIR="${CI_PROJECT_DIR:-/workspace}"
PARASOFT_INSTALL_DIR="${PARASOFT_INSTALL_DIR:-/opt/parasoft/jtest}"

cd /workspace

# =============================================================================
# SCAN — mirrors the CI component script exactly.
# When the CI component changes, update only this section.
# =============================================================================

cat > report.properties <<PROPS
report.format=txt,pdf,xml,html,sast-gitlab,sate
report.custom.extension=xml
report.scontrol=min
scontrol.rep.type=git
scontrol.rep.git.url=${CI_PROJECT_URL}
scontrol.branch=${BRANCH}
scontrol.rep.git.workspace=${CI_PROJECT_DIR}
PROPS

./gradlew clean assemble

./gradlew jtest \
  -I "${PARASOFT_INSTALL_DIR}/integration/gradle/init.gradle" \
  "-Djtest.config=dtp://Recommended-Rules-for-Java" \
  "-Djtest.settings=report.properties" \
  "-Djtest.report=/workspace/.appsec-results/parasoft-reports" \
  "-Djtest.exclude=path:**/build/**"

# Severity gate (mirrors CI component): exit 1 if severity id < 3 (Critical or High)
REPORT="/workspace/.appsec-results/parasoft-reports/report.xml"
if [ -f "$REPORT" ]; then
  if xmllint --xpath \
    "/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id<3]" \
    "$REPORT" >/dev/null 2>&1; then
    echo "Critical or high issues present"
    exit 1
  else
    echo "No critical or high issues present"
  fi
fi

#!/usr/bin/env sh
# =============================================================================
# Scanner      : Fortify SAST
# Target       : Source tree in analyzer workspace
# CI component : lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
# Last synced  : 2026-07-15
# Image env var: FORTIFY_SAST_IMAGE (full ref — set from the profile's image: by load-prefs.sh)
# Languages    : maven, gradle, python, javascript
# Output       : fortify-sast.fpr
#
# HOW TO UPDATE
# When the CI component's script block changes:
#   1. Update the SCAN section below to match the component script.
#   2. If the component changes analyzer variables or output names, update
#      SKILL.md and the smoke test parser at the same time.
#   3. Update "Last synced" above.
#   Image selection happens in SKILL.md's docker run, not in this script.
# =============================================================================
set -eu

CI_PROJECT_DIR="${CI_PROJECT_DIR:-/workspace}"
RESULTS="${CI_PROJECT_DIR}/.appsec-results"
OUT_DIR="${RESULTS}"
APP_NAME="${APP_NAME:-$(basename "${CI_PROJECT_DIR}")}"
SOURCE_PATH="${SOURCE_PATH:-src}"
FORTIFY_LANGUAGE="${FORTIFY_LANGUAGE:-}"
FPR_PATH="${OUT_DIR}/fortify-sast.fpr"

cd "${CI_PROJECT_DIR}"
mkdir -p "${OUT_DIR}"
rm -f "${FPR_PATH}"

FILTER_ARGS=
if [ -f "filter_list.txt" ]; then
  FILTER_ARGS="-filter filter_list.txt"
fi

# =============================================================================
# SCAN — mirrors the private catalog Fortify SAST component script.
# =============================================================================

sourceanalyzer -b "${APP_NAME}" -clean

case "${FORTIFY_LANGUAGE}" in
  maven)
    sourceanalyzer -b "${APP_NAME}" \
      mvn clean install -s "${MAVEN_SETTINGS:-settings.xml}" -DskipTests
    ;;
  gradle)
    sourceanalyzer -b "${APP_NAME}" \
      ./gradlew -p "${SOURCE_PATH}" clean assemble \
      "-Partifactory_user=${ARTIFACTORY_USER:-}" \
      "-Partifactory_password=${ARTIFACTORY_PASSWORD:-}"
    sourceanalyzer -b "${APP_NAME}" "${SOURCE_PATH}"
    ;;
  python)
    sourceanalyzer -b "${APP_NAME}" \
      -python-version 3 \
      "${SOURCE_PATH}"
    ;;
  javascript)
    sourceanalyzer -b "${APP_NAME}" \
      -Dcom.fortify.sca.follow.imports=false \
      "${SOURCE_PATH}"
    ;;
  "")
    echo "ERROR: FORTIFY_LANGUAGE is required (maven|gradle|python|javascript)" >&2
    exit 2
    ;;
  *)
    echo "ERROR: unsupported FORTIFY_LANGUAGE=${FORTIFY_LANGUAGE} (expected maven|gradle|python|javascript)" >&2
    exit 2
    ;;
esac

if [ -n "${FILTER_ARGS}" ]; then
  sourceanalyzer -b "${APP_NAME}" -scan -f "${FPR_PATH}" -filter filter_list.txt
else
  sourceanalyzer -b "${APP_NAME}" -scan -f "${FPR_PATH}"
fi

if command -v FPRUtility >/dev/null 2>&1; then
  FPRUtility -information -signature -search \
    -query "[fortify priority order]:critical OR [fortify priority order]:high AND [issue age]:!removed AND suppressed:false" \
    -filterSet "Security Auditor View" \
    -project "${FPR_PATH}" || true
fi

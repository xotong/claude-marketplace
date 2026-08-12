#!/usr/bin/env sh
# =============================================================================
# Scanner      : Fortify SAST
# Target       : Source tree in analyzer workspace
# CI component : lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
# Last synced  : 2026-08-12
# Image env var: FORTIFY_SAST_IMAGE (full ref — set from the profile's image: by load-prefs.sh)
# Languages    : maven, gradle, python, javascript, go
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
    sourceanalyzer -debug -verbose -b "${APP_NAME}" \
      mvn clean install -s "${MAVEN_SETTINGS:-settings.xml}" -DskipTests
    ;;
  gradle)
    # The component runs $[[ inputs.source-path ]]/gradlew (template.yml:130), not
    # ./gradlew. Those are different files whenever source-path is not "." — so
    # running the wrong one means this scan and the CI job disagree about which
    # build they even executed. Prefer CI's path; fall back to a root wrapper
    # rather than refusing to scan, but name the CI consequence, because catching
    # that here is the entire point of running this before pushing.
    if [ -x "${SOURCE_PATH}/gradlew" ]; then
      GRADLEW="${SOURCE_PATH}/gradlew"
    elif [ -x ./gradlew ]; then
      GRADLEW=./gradlew
      echo "WARNING: CI runs ${SOURCE_PATH}/gradlew, which does not exist here." >&2
      echo "WARNING:   Scanning with ./gradlew instead: this scan will pass and the CI job" >&2
      echo "WARNING:   will fail. Move the wrapper into ${SOURCE_PATH}/, or set the" >&2
      echo "WARNING:   component input source-path: . to match." >&2
    else
      echo "ERROR: no gradle wrapper at ${SOURCE_PATH}/gradlew or ./gradlew" >&2
      echo "ERROR:   The component requires a working gradle wrapper in the repository." >&2
      exit 2
    fi
    sourceanalyzer -b "${APP_NAME}" \
      "${GRADLEW}" -p "${SOURCE_PATH}" clean assemble \
      "-Partifactory_user=${ARTIFACTORY_USER:-}" \
      "-Partifactory_password=${ARTIFACTORY_PASSWORD:-}"
    sourceanalyzer -b "${APP_NAME}" "${SOURCE_PATH}"
    ;;
  python)
    sourceanalyzer -b "${APP_NAME}" \
      -debug-verbose \
      -python-version 3 \
      "${SOURCE_PATH}"
    ;;
  javascript)
    sourceanalyzer -b "${APP_NAME}" \
      -debug-verbose \
      -Dcom.fortify.sca.follow.imports=false \
      "${SOURCE_PATH}"
    ;;
  go)
    # Mirrors the component's <job-name>-go job (template.yml:151-158):
    #   sourceanalyzer -b $CI_JOB_ID -clean
    #   (cd $[[ inputs.source-path ]] && go mod download)
    #   sourceanalyzer -b $CI_JOB_ID -debug-verbose $[[ inputs.source-path ]]
    # The -clean above already ran; go mod download resolves the module graph so
    # sourceanalyzer can follow imports. Note the component omits
    # -Dcom.fortify.sca.follow.imports=false here, unlike the javascript arm.
    ( cd "${SOURCE_PATH}" && go mod download )
    sourceanalyzer -b "${APP_NAME}" \
      -debug-verbose \
      "${SOURCE_PATH}"
    ;;
  "")
    echo "ERROR: FORTIFY_LANGUAGE is required (maven|gradle|python|javascript|go)" >&2
    exit 2
    ;;
  *)
    echo "ERROR: unsupported FORTIFY_LANGUAGE=${FORTIFY_LANGUAGE} (expected maven|gradle|python|javascript|go)" >&2
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

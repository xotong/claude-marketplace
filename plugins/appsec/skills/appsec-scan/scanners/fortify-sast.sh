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
# One FPR and one Fortify build ID per unit. run-scan.sh runs this script once
# per discovered (source-path, language) unit, exactly as CI includes the
# component once per service; sharing either name across units would make each
# `-clean` wipe the previous unit's build and leave one report standing for a
# repository that had several. Both default to the single-unit values, so a
# root-only project is byte-identical to before.
FPR_NAME="${FPR_NAME:-fortify-sast.fpr}"
FPR_PATH="${OUT_DIR}/${FPR_NAME}"
FORTIFY_BUILD_ID="${FORTIFY_BUILD_ID:-${APP_NAME}}"

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

sourceanalyzer -b "${FORTIFY_BUILD_ID}" -clean

case "${FORTIFY_LANGUAGE}" in
  maven)
    sourceanalyzer -debug -verbose -b "${FORTIFY_BUILD_ID}" \
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
    sourceanalyzer -b "${FORTIFY_BUILD_ID}" \
      "${GRADLEW}" -p "${SOURCE_PATH}" clean assemble \
      "-Partifactory_user=${ARTIFACTORY_USER:-}" \
      "-Partifactory_password=${ARTIFACTORY_PASSWORD:-}"
    sourceanalyzer -b "${FORTIFY_BUILD_ID}" "${SOURCE_PATH}"
    ;;
  python)
    # SCA does not run the code, it resolves imports statically, so an import it
    # cannot resolve is dataflow it cannot follow. Upstream measured it on crAPI:
    # empty venv 28 vulnerabilities, populated venv 46. This arm used to pass no
    # -python-path at all — thinner than the component, and silent about it.
    #
    # Two tiers, and never a third that quietly reaches the public internet:
    #   uv settings configured -> replicate CI exactly (uv, interpreter and
    #                             packages all from the configured mirror)
    #   not configured         -> stdlib only, and SAY the scan is degraded
    PY_RESOLUTION=stdlib-only
    PYPATH=
    if [ -n "${UV_INSTALLER_BASE:-}" ] && [ -n "${UV_VERSION:-}" ]; then
      echo "[fortify] installing uv ${UV_VERSION} from ${UV_INSTALLER_BASE}" >&2
      if curl -LsSf "${UV_INSTALLER_BASE}/${UV_VERSION}/uv-installer.sh" | sh >&2 &&
         . "$HOME/.local/bin/env" 2>/dev/null; then
        [ -z "${FORTIFY_PYTHON_VERSION:-}" ] || uv python install "${FORTIFY_PYTHON_VERSION}" >&2 || true
        if uv venv >&2 && . .venv/bin/activate; then
          if [ -f "${SOURCE_PATH}/requirements.txt" ]; then
            REQ="${SOURCE_PATH}/requirements.txt"
            # Bulk install is atomic: one unbuildable package (psycopg2 wants
            # pg_config, which a scanner image has no reason to ship) must
            # degrade the venv, not empty it and take the scan with it.
            uv pip install -r "$REQ" >&2 || {
              echo "[fortify] bulk install failed; retrying per-package" >&2
              UNRESOLVED=0
              while read -r pkg; do
                pkg=$(printf '%s' "$pkg" | sed 's/#.*//; s/[[:space:]]*$//')
                case "$pkg" in ''|-*) continue ;; esac
                uv pip install "$pkg" >/dev/null 2>&1 || {
                  echo "[fortify]   unresolvable: $pkg" >&2
                  UNRESOLVED=$((UNRESOLVED + 1))
                }
              done <"$REQ"
              [ "$UNRESOLVED" -eq 0 ] || echo "[fortify] ${UNRESOLVED} package(s) unresolvable — resolution is partial" >&2
            }
          elif [ -f "${SOURCE_PATH}/pyproject.toml" ]; then
            uv pip install "${SOURCE_PATH}" >&2 || echo "[fortify] project install failed" >&2
          fi
          PYPATH=$(ls -d .venv/lib*/python*/site-packages 2>/dev/null | paste -sd: -)
          [ -z "$PYPATH" ] || PY_RESOLUTION=full
        fi
      else
        echo "[fortify] uv install failed — falling back to stdlib-only resolution" >&2
      fi
    fi

    # SCA bundles only a subset of the stdlib and ignores PYTHONPATH, so the
    # interpreter's own stdlib must be named or logging/json/textwrap stay
    # unresolved. Worth it even in the degraded tier: upstream saw the scan get
    # both more accurate AND faster (349s -> 259s).
    STDLIB=$(python -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])' 2>/dev/null || true)
    if [ -n "$STDLIB" ] && [ -d "$STDLIB" ]; then
      PYPATH="${PYPATH:+$PYPATH:}$STDLIB"
    fi

    if [ "$PY_RESOLUTION" != full ]; then
      echo "APPSEC-PY-DEGRADED: third-party imports were NOT resolved, so this scan finds less than CI will. Set settings.python_runtime.{uv_version,uv_installer_base,uv_python_install_mirror} to your mirror." >&2
    fi

    # Opt-in and all-or-nothing: -disable-template-autodiscover REPLACES
    # discovery, so naming one directory in a repo with two loses the second.
    set --
    if [ -n "${FORTIFY_PYTHON_TEMPLATE_DIRS:-}" ]; then
      set -- -django-template-dirs "${FORTIFY_PYTHON_TEMPLATE_DIRS}" \
             -jinja-template-dirs "${FORTIFY_PYTHON_TEMPLATE_DIRS}" \
             -disable-template-autodiscover
    fi

    echo "[fortify] python-path: ${PYPATH:-<none>} (resolution: ${PY_RESOLUTION})" >&2
    sourceanalyzer -b "${FORTIFY_BUILD_ID}" \
      -debug-verbose \
      ${PYPATH:+-python-path "$PYPATH"} \
      -python-version 3 \
      "$@" \
      "${SOURCE_PATH}"
    ;;
  javascript)
    sourceanalyzer -b "${FORTIFY_BUILD_ID}" \
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
    sourceanalyzer -b "${FORTIFY_BUILD_ID}" \
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
  sourceanalyzer -b "${FORTIFY_BUILD_ID}" -scan -f "${FPR_PATH}" -filter filter_list.txt
else
  sourceanalyzer -b "${FORTIFY_BUILD_ID}" -scan -f "${FPR_PATH}"
fi

if command -v FPRUtility >/dev/null 2>&1; then
  FPRUtility -information -signature -search \
    -query "[fortify priority order]:critical OR [fortify priority order]:high AND [issue age]:!removed AND suppressed:false" \
    -filterSet "Security Auditor View" \
    -project "${FPR_PATH}" || true
fi

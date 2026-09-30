#!/usr/bin/env sh
# =============================================================================
# Scanner      : Fortify SAST
# Target       : Source tree in analyzer workspace
# CI component : lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
# Last synced  : 2026-08-19
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
# JVM CA trust for Maven/Gradle — settings.ca_bundle (ADDITIONAL_CA_CERT_BUNDLE)
# reaches curl/python (see appsec_trust_ca below, used for uv) but never the
# JVM itself, so a Maven/Gradle build behind TLS inspection (a corporate proxy
# that resigns every certificate) fails to resolve dependencies with a trust
# error that reads like a broken mirror. Copy the JDK's own cacerts into a temp
# truststore and import each certificate from the bundle into it; a
# certificate that fails to import is skipped, not fatal. No-op when no bundle
# is mounted or no keytool is on PATH — every other estate is unchanged.
# =============================================================================
if [ -n "${ADDITIONAL_CA_CERT_BUNDLE:-}" ] && [ -r "${ADDITIONAL_CA_CERT_BUNDLE}" ] && command -v keytool >/dev/null 2>&1; then
  CA_CACERTS=
  if [ -n "${JAVA_HOME:-}" ] && [ -r "${JAVA_HOME}/lib/security/cacerts" ]; then
    CA_CACERTS="${JAVA_HOME}/lib/security/cacerts"
  else
    CA_KEYTOOL_BIN=$(command -v keytool)
    CA_CANDIDATE=$(dirname "$(dirname "${CA_KEYTOOL_BIN}")")/lib/security/cacerts
    [ -r "${CA_CANDIDATE}" ] && CA_CACERTS="${CA_CANDIDATE}"
  fi
  if [ -n "${CA_CACERTS}" ]; then
    CA_TRUSTSTORE=$(mktemp)
    cp "${CA_CACERTS}" "${CA_TRUSTSTORE}"
    CA_CERT_N=0
    CA_IMPORTED=0
    CA_CERT_FILE=
    while IFS= read -r CA_LINE; do
      case "${CA_LINE}" in
        *"-----BEGIN CERTIFICATE-----"*)
          CA_CERT_N=$((CA_CERT_N + 1))
          CA_CERT_FILE=$(mktemp)
          printf '%s\n' "${CA_LINE}" >"${CA_CERT_FILE}"
          ;;
        *"-----END CERTIFICATE-----"*)
          if [ -n "${CA_CERT_FILE}" ]; then
            printf '%s\n' "${CA_LINE}" >>"${CA_CERT_FILE}"
            if keytool -importcert -noprompt -trustcacerts \
                -alias "appsec-ca-${CA_CERT_N}" \
                -keystore "${CA_TRUSTSTORE}" -storepass changeit \
                -file "${CA_CERT_FILE}" >/dev/null 2>&1; then
              CA_IMPORTED=$((CA_IMPORTED + 1))
            else
              echo "[fortify] keytool could not import certificate #${CA_CERT_N} from settings.ca_bundle; skipping" >&2
            fi
            rm -f "${CA_CERT_FILE}"
            CA_CERT_FILE=
          fi
          ;;
        *)
          [ -z "${CA_CERT_FILE}" ] || printf '%s\n' "${CA_LINE}" >>"${CA_CERT_FILE}"
          ;;
      esac
    done <"${ADDITIONAL_CA_CERT_BUNDLE}"
    if [ "${CA_IMPORTED}" -gt 0 ]; then
      JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }-Djavax.net.ssl.trustStore=${CA_TRUSTSTORE} -Djavax.net.ssl.trustStorePassword=changeit"
      export JAVA_TOOL_OPTIONS
      echo "[fortify] imported ${CA_IMPORTED} certificate(s) from settings.ca_bundle into a JVM truststore for Maven/Gradle" >&2
      echo "[fortify] JAVA_TOOL_OPTIONS: ${JAVA_TOOL_OPTIONS}" >&2
    else
      rm -f "${CA_TRUSTSTORE}"
    fi
  else
    echo "[fortify] settings.ca_bundle is set but no JDK cacerts could be found; Maven/Gradle builds will not trust it" >&2
  fi
fi

# Trust settings.ca_bundle for every non-JVM tool (curl, python/requests, uv, go).
#
# `update-ca-trust` is the usual way to install a CA, and it cannot run
# here: verified against fortify-sca 25.2.0, the container is uid 1000 and
# /etc/pki/ca-trust/source/anchors is not writable. Concatenating the
# system bundle with ours into a writable file and exporting the standard
# variables reaches the same end without root — and unlike `curl --cacert`
# it also covers each tool's OWN downloads (uv's interpreter and packages,
# go's module fetches). Returns 1 when no bundle is mounted.
appsec_trust_ca() {
  [ -n "${ADDITIONAL_CA_CERT_BUNDLE:-}" ] && [ -r "${ADDITIONAL_CA_CERT_BUNDLE}" ] || return 1
  _b=/tmp/appsec-ca-bundle.pem
  : >"$_b" || return 1
  for _sys in /etc/pki/tls/certs/ca-bundle.crt \
              /etc/ssl/certs/ca-certificates.crt \
              /etc/ssl/cert.pem; do
    [ -r "$_sys" ] && cat "$_sys" >>"$_b" && break
  done
  cat "${ADDITIONAL_CA_CERT_BUNDLE}" >>"$_b" || return 1
  # curl, python/requests, uv and go each read one of these.
  export SSL_CERT_FILE="$_b" CURL_CA_BUNDLE="$_b" REQUESTS_CA_BUNDLE="$_b"
  return 0
}

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
    # translation-mode mirrors the component input of the same name.
    #   normal (default)  translate only our own code. No install, no venv, no uv,
    #                     no network. The component's own description: seconds to
    #                     minutes, complete coverage of your code, no dataflow
    #                     through third-party libraries.
    #   full              also follow imports into dependencies. The component
    #                     warns this "CAN TAKE HOURS" and on a 230-package service
    #                     "exceeded 3h and produced no report".
    #
    # Normal is NOT a degraded scan -- it is a mode CI runs too, and reporting it
    # as degraded would cry wolf on every default run. Only `full` that could not
    # be honoured is degraded, because then the result is thinner than the one
    # that was asked for.
    TRANSLATION_MODE="${FORTIFY_TRANSLATION_MODE:-normal}"
    PY_RESOLUTION="$TRANSLATION_MODE"
    PYPATH=
    if [ "$TRANSLATION_MODE" = full ] && [ -n "${UV_INSTALLER_BASE:-}" ] && [ -n "${UV_VERSION:-}" ]; then
      echo "[fortify] installing uv ${UV_VERSION} from ${UV_INSTALLER_BASE}" >&2
      UV_URL="${UV_INSTALLER_BASE}/${UV_VERSION}/uv-installer.sh"
      UV_SH=$(mktemp)

      # Ask before assuming: if TLS already verifies, there is nothing to fix and
      # nothing to weaken.
      #
      # Deliberately WITHOUT -f. With it, an HTTP 404 exits 22 and is
      # indistinguishable from a certificate failure — so a mirror that is
      # perfectly trusted but simply does not carry this uv version would be
      # diagnosed as "TLS could not be verified", and on an estate with
      # allow_insecure_uv_download set that would disable verification to solve a
      # missing file. Without -f, a non-zero exit means the transport itself
      # failed; the real fetch below still uses -f and reports the 404 as a 404.
      tls_ok() { curl -sS --max-time 30 -o /dev/null "$UV_URL" 2>/dev/null; }

      UV_GOT=false
      UV_TLS=verified
      if tls_ok; then
        UV_GOT=true
      elif appsec_trust_ca && tls_ok; then
        UV_TLS=ca-bundle
        echo "[fortify] TLS verified via settings.ca_bundle; exported for uv and pip too" >&2
        UV_GOT=true
      elif [ "${ALLOW_INSECURE_UV_DOWNLOAD:-false}" = true ]; then
        UV_TLS=insecure
        UV_GOT=true
      else
        echo "[fortify] TLS to ${UV_INSTALLER_BASE} could not be verified." >&2
        echo "[fortify]   Set settings.ca_bundle to your internal CA. If it genuinely cannot" >&2
        echo "[fortify]   verify, settings.python_runtime.allow_insecure_uv_download: true" >&2
        echo "[fortify]   permits an unverified download — read what that means first." >&2
      fi

      if $UV_GOT; then
        if [ "$UV_TLS" = insecure ]; then
          echo "APPSEC-INSECURE-TLS: uv is being downloaded with certificate verification DISABLED (-k) and piped to sh." >&2
          echo "APPSEC-INSECURE-TLS:   Anything able to intercept that request could run arbitrary code in this scanner." >&2
          echo "APPSEC-INSECURE-TLS:   Fix settings.ca_bundle, then set allow_insecure_uv_download: false." >&2
          curl -LsSf -k "$UV_URL" -o "$UV_SH" || UV_GOT=false
        else
          curl -LsSf "$UV_URL" -o "$UV_SH" || UV_GOT=false
        fi
      fi

      if $UV_GOT && sh "$UV_SH" >&2 && . "$HOME/.local/bin/env" 2>/dev/null; then
        rm -f "$UV_SH"
        [ -z "${FORTIFY_PYTHON_VERSION:-}" ] || uv python install "${FORTIFY_PYTHON_VERSION}" >&2 || true
        # Private to this container, not /workspace/.venv: /workspace is the
        # user's repository, shared by every unit run-scan.sh runs in parallel,
        # so a venv there would be rebuilt under a neighbouring python unit.
        APPSEC_VENV="$(mktemp -d)/venv"
        if uv venv "$APPSEC_VENV" >&2 && . "$APPSEC_VENV/bin/activate"; then
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
          PYPATH=$(ls -d "$APPSEC_VENV"/lib*/python*/site-packages 2>/dev/null | paste -sd: -)
          [ -z "$PYPATH" ] || PY_RESOLUTION=full-achieved
        fi
      else
        echo "[fortify] uv install failed — falling back to stdlib-only resolution" >&2
      fi
    fi

    # SCA bundles only a subset of the stdlib and ignores PYTHONPATH, so the
    # interpreter's own stdlib must be named or logging/json/textwrap stay
    # unresolved. Worth it even in the degraded tier: upstream saw the scan get
    # both more accurate AND faster (349s -> 259s).
    # `python` exists only inside an activated venv; the bare fortify-sca image
    # ships python3 and no python at all. The component's own template gets away
    # with `python` because it always runs after `activate` — the degraded tier
    # here does not, and using `python` made this silently resolve nothing, which
    # is the entire value of the degraded tier.
    PY_BIN=python
    command -v "$PY_BIN" >/dev/null 2>&1 || PY_BIN=python3
    STDLIB=$("$PY_BIN" -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])' 2>/dev/null || true)
    if [ -n "$STDLIB" ] && [ -d "$STDLIB" ]; then
      PYPATH="${PYPATH:+$PYPATH:}$STDLIB"
    fi

    case "$TRANSLATION_MODE:$PY_RESOLUTION" in
      normal:*)
        echo "[fortify] translation-mode=normal: own code only, dependencies not translated (matches the component default)." >&2
        ;;
      full:full-achieved) ;;
      full:*)
        # Asked for full, could not deliver it. THIS is the degraded case: the
        # result is thinner than the mode that was requested, and if CI runs full
        # the two now disagree.
        echo "APPSEC-PY-DEGRADED: translation-mode=full was requested but dependencies could not be resolved, so this scan finds less than a full CI scan will. Set settings.python_runtime.{uv_version,uv_installer_base,uv_python_install_mirror} to your mirror, or set translation_mode: normal to match." >&2
        ;;
    esac

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
    #
    # go reads SSL_CERT_FILE, not the JVM truststore above, so without this a
    # TLS-inspecting proxy fails every module fetch with "x509: certificate
    # signed by unknown authority" and the unit produces no report.
    appsec_trust_ca || :
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

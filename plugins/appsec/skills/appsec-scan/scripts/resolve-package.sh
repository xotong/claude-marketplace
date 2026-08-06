#!/usr/bin/env bash
# =============================================================================
# Ask the configured package registry whether a specific package version exists.
#
# This runs BEFORE the fix loop, not during it. The loop is capped at 5
# iterations; spending them attempting upgrades to versions the mirror does not
# carry burns the budget on work that can never succeed and leaves the developer
# with a confusing failure instead of a clear ask.
#
# URL shapes are TEMPLATES from config, never guessed here. Artifactory exposes a
# different API per ecosystem and per deployment, so the admin declares the exact
# URL and this script only substitutes and probes -- the same principle as
# gitlab_instance in scanner-preferences.yaml.
#
# Placeholders: {package} {version} {group_path} {artifact} {module}
#
# Verdicts (stdout, one word):
#   available  registry answered 200 (and, for listing-style URLs, the body
#              mentions the version)
#   absent     registry answered 404 -- the mirror does not carry it
#   unknown    no template configured, no curl, timeout, auth failure, or any
#              other status. NEVER guessed as available or absent: a registry we
#              could not reach is not evidence either way.
#
# Usage: resolve-package.sh <ecosystem> <package> <version> <url_template> [token_env]
# =============================================================================
set -euo pipefail

ECOSYSTEM=${1:-}
PACKAGE=${2:-}
VERSION=${3:-}
TEMPLATE=${4:-}
TOKEN_ENV=${5:-}

verdict() { printf '%s\n' "$1"; exit 0; }

[ -n "$PACKAGE" ] || verdict unknown
[ -n "$TEMPLATE" ] || verdict unknown
command -v curl >/dev/null 2>&1 || verdict unknown

# Maven coordinates arrive as group:artifact; the repository layout needs the
# group's dots turned into path separators.
group_path=""
artifact="$PACKAGE"
case "$ECOSYSTEM" in
  maven)
    case "$PACKAGE" in
      *:*)
        group_path=$(printf '%s' "${PACKAGE%%:*}" | tr '.' '/')
        artifact="${PACKAGE##*:}"
        ;;
      *) verdict unknown ;;  # not a coordinate we can lay out; do not guess
    esac
    ;;
esac

url=$TEMPLATE
url=${url//\{package\}/$PACKAGE}
url=${url//\{version\}/$VERSION}
url=${url//\{group_path\}/$group_path}
url=${url//\{artifact\}/$artifact}
url=${url//\{module\}/$PACKAGE}

# Token via curl --config so it never appears in argv or process listings,
# matching how catalog.sh handles the catalogue PAT.
curl_cfg=""
body_file=""
# Must return 0 unconditionally. As an EXIT trap its status becomes the script's
# exit status, and the common case here is anonymous read with no token file to
# remove -- a bare `[ -n "$curl_cfg" ] && rm` would then exit 1 on every probe.
cleanup() {
  [ -n "$curl_cfg" ] && rm -f "$curl_cfg"
  [ -n "$body_file" ] && rm -f "$body_file"
  return 0
}
trap cleanup EXIT

auth_args=()
if [ -n "$TOKEN_ENV" ]; then
  token_value=$(printenv "$TOKEN_ENV" 2>/dev/null || true)
  if [ -n "$token_value" ]; then
    curl_cfg=$(mktemp) || verdict unknown
    printf 'header = "Authorization: Bearer %s"\n' "$token_value" >"$curl_cfg"
    auth_args=(--config "$curl_cfg")
  fi
fi

body_file=$(mktemp) || verdict unknown

status=$(curl -sSL \
  --max-time "${PACKAGE_PROBE_TIMEOUT:-10}" \
  -o "$body_file" \
  -w '%{http_code}' \
  "${auth_args[@]}" \
  "$url" 2>/dev/null || printf '000')

case "$status" in
  200)
    # A template carrying {version} addresses one exact version, so 200 settles
    # it. A listing-style URL (pypi simple index) returns the whole package, so
    # the version has to actually appear in the body.
    case "$TEMPLATE" in
      *'{version}'*) verdict available ;;
      *)
        if [ -z "$VERSION" ]; then
          verdict unknown
        elif grep -qF -- "$VERSION" "$body_file"; then
          verdict available
        else
          verdict absent
        fi
        ;;
    esac
    ;;
  404|410) verdict absent ;;
  *)       verdict unknown ;;
esac

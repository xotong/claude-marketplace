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
#   available     registry answered 200 (and, for listing-style URLs, the body
#                 mentions the version)
#   absent        registry answered 404 -- the mirror does not carry it
#   unauthorized  registry answered 401/403. Callers must treat this exactly as
#                 `unknown` when deciding a finding's status -- being refused is
#                 no more evidence of absence than a timeout is -- but it is a
#                 SEPARATE word because the two need opposite handling. A
#                 timeout may fix itself; a rejected credential never will, and
#                 collapsing it into `unknown` is what let a non-anonymous JFrog
#                 turn every probe into a shrug with nothing naming the cause.
#   unknown       no template configured, no curl, timeout, or any other status.
#                 NEVER guessed as available or absent: a registry we could not
#                 reach is not evidence either way.
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
        # Pure bash, no `tr`: a minimal airgapped userland need not carry
        # coreutils, and under `set -e` the missing binary exited 127 with no
        # verdict on stdout at all, where the contract promises `unknown`.
        # The replacement must come from a variable -- bash 3.2 renders both
        # ${g//./\/} and ${g//./"/"} literally, backslash and quotes included.
        _slash=/
        group_path="${PACKAGE%%:*}"
        group_path="${group_path//./$_slash}"
        artifact="${PACKAGE##*:}"
        ;;
      *) verdict unknown ;;  # not a coordinate we can lay out; do not guess
    esac
    ;;
esac

url=$TEMPLATE
module=$PACKAGE
if [ "$ECOSYSTEM" = "go" ]; then
  # GOPROXY escapes each uppercase ASCII letter as ! followed by its lowercase
  # form. Keep every other placeholder unchanged: this rule belongs only to Go
  # module paths substituted into {module}.
  #
  # Done in pure bash rather than sed|tr for the same reason as group_path
  # above: no coreutils on the host used to mean exit 127 and no verdict. One
  # global substitution per letter is safe in any order -- neither `!` nor a
  # lowercase letter is ever an uppercase letter, so nothing is re-escaped.
  # `${var,,}` is bash 4 only; this skill must run on macOS bash 3.2.
  _upper=ABCDEFGHIJKLMNOPQRSTUVWXYZ
  _lower=abcdefghijklmnopqrstuvwxyz
  _i=0
  while [ "$_i" -lt 26 ]; do
    module=${module//${_upper:$_i:1}/!${_lower:$_i:1}}
    _i=$(( _i + 1 ))
  done
fi
url=${url//\{package\}/$PACKAGE}
url=${url//\{version\}/$VERSION}
url=${url//\{group_path\}/$group_path}
url=${url//\{artifact\}/$artifact}
url=${url//\{module\}/$module}

# Token via curl --config so it never appears in argv or process listings,
# matching how catalog.sh handles the catalogue PAT.
curl_cfg=""
body_file=""
# Must return 0 unconditionally. As an EXIT trap its status becomes the script's
# exit status, and the common case here is anonymous read with no token file to
# remove -- a bare `[ -n "$curl_cfg" ] && rm` would then exit 1 on every probe.
# `|| :` because `rm` itself may be missing on a minimal userland: an EXIT trap
# that dies with 127 turns a printed `unknown` into a crashing probe, which is
# exactly what this script promises never to do.
cleanup() {
  [ -n "$curl_cfg" ] && rm -f "$curl_cfg" 2>/dev/null || :
  [ -n "$body_file" ] && rm -f "$body_file" 2>/dev/null || :
  return 0
}
trap cleanup EXIT

if [ -n "$TOKEN_ENV" ]; then
  token_value=$(printenv "$TOKEN_ENV" 2>/dev/null || true)
  if [ -n "$token_value" ]; then
    curl_cfg=$(mktemp) || verdict unknown
    printf 'header = "Authorization: Bearer %s"\n' "$token_value" >"$curl_cfg"
  fi
fi

body_file=$(mktemp) || verdict unknown

if [ -n "$curl_cfg" ]; then
  status=$(curl -sSL \
    --max-time "${PACKAGE_PROBE_TIMEOUT:-10}" \
    -o "$body_file" \
    -w '%{http_code}' \
    --config "$curl_cfg" \
    "$url" 2>/dev/null || printf '000')
else
  status=$(curl -sSL \
    --max-time "${PACKAGE_PROBE_TIMEOUT:-10}" \
    -o "$body_file" \
    -w '%{http_code}' \
    "$url" 2>/dev/null || printf '000')
fi

case "$status" in
  200)
    # A template carrying {version} addresses one exact version, so 200 settles
    # it. A listing-style URL (pypi simple index) returns the whole package, so
    # the version has to actually appear in the body.
    case "$TEMPLATE" in
      *'{version}'*) verdict available ;;
      *)
        # $(<file) is a bash builtin and the match is a quoted case pattern, so
        # no `grep` is needed. A missing grep used to report `absent` here --
        # a false mirroring request built on a tool that never ran.
        if [ -z "$VERSION" ]; then
          verdict unknown
        else
          body=$(<"$body_file")
          case $body in
            *"$VERSION"*) verdict available ;;
            *)            verdict absent ;;
          esac
        fi
        ;;
    esac
    ;;
  404|410) verdict absent ;;
  # 000 is the `|| printf '000'` short-circuit above: curl never got an answer.
  # That, timeouts and 5xx stay `unknown` -- only an actual refusal is config.
  401|403) verdict unauthorized ;;
  *)       verdict unknown ;;
esac

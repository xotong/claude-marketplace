#!/usr/bin/env bash
# =============================================================================
# Ask the configured container registry whether one specific base image tag is
# obtainable before the fix loop proposes rebuilding on it.
#
# A base-image remediation is only useful when the estate's internal mirror
# carries that image. Probing first preserves the loop's limited iterations and
# turns mirror gaps into an actionable, batched request for the platform team.
# Registry refs are TEMPLATES from admin config, never guessed here: repository
# layout is a deployment decision. Placeholders: {image} {tag}
#
# Verdicts (stdout, one word; every verdict exits 0):
#   available  manifest metadata was found, or the fallback pull succeeded
#   absent     the registry definitively said the image or manifest is missing
#   unknown    missing input/runtime, auth failure, network failure, or any
#              unrecognised error. Unknown is NEVER upgraded to absent: being
#              unable to ask the registry is not evidence that an image is
#              missing and must not manufacture work for the platform team.
#
# Usage: resolve-base-image.sh <image> <tag> <url_template> [runtime]
# =============================================================================
set -euo pipefail

IMAGE=${1:-}
TAG=${2:-}
TEMPLATE=${3:-}
RUNTIME=${4:-${RUNTIME:-${CONTAINER_RUNTIME:-auto}}}

verdict() { printf '%s\n' "$1"; exit 0; }

[ -n "$IMAGE" ] || verdict unknown
[ -n "$TAG" ] || verdict unknown
[ -n "$TEMPLATE" ] || verdict unknown

# The runtime argument may be an explicit executable (including a full path).
# With no explicit choice, prefer Docker and then Podman, matching the skill's
# normal runtime detection order without depending on another helper script.
case "$RUNTIME" in
  ""|auto)
    if command -v docker >/dev/null 2>&1; then
      RUNTIME=docker
    elif command -v podman >/dev/null 2>&1; then
      RUNTIME=podman
    else
      verdict unknown
    fi
    ;;
  *)
    command -v "$RUNTIME" >/dev/null 2>&1 || verdict unknown
    ;;
esac

ref=$TEMPLATE
ref=${ref//\{image\}/$IMAGE}
ref=${ref//\{tag\}/$TAG}

# Bash 3.2 supports nocasematch for both case and [[ ... ]]. It lets these
# classifiers match Docker and Podman spelling/capitalisation without `tr`.
shopt -s nocasematch

# is_auth_error lives in classify-error.sh: run-scan.sh and resolve-image.sh need
# the same judgement, and three divergent copies of "what counts as an auth
# failure" is exactly how one caller ends up calling a 401 a network outage.
# Pure parameter expansion, no `dirname`: a minimal airgapped userland need not
# carry coreutils, and these helpers are tested under a stripped PATH.
_ce_dir=${BASH_SOURCE[0]%/*}
if [ "$_ce_dir" = "${BASH_SOURCE[0]}" ]; then _ce_dir=.; fi
# shellcheck source=scripts/classify-error.sh
. "$_ce_dir/classify-error.sh"

is_absent_error() {
  case "$1" in
    *"manifest unknown"* | *"not found"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Fall back only when the runtime rejects the manifest-inspect operation itself.
# Registry, daemon, network, and credential failures must not trigger a large
# image pull merely because manifest inspection failed.
is_manifest_inspect_unsupported() {
  case "$1" in
    *"unknown command"*manifest* | *manifest*"unknown command"* | \
    *"unrecognized command"*manifest* | *manifest*"unrecognized command"* | \
    *"unrecognised command"*manifest* | *manifest*"unrecognised command"* | \
    *"no such command"*manifest* | *manifest*"no such command"* | \
    *manifest*"not a"*command* | *manifest*"not a recognized command"* | \
    *command*manifest*"not found"* | *manifest*command*"not found"* | \
    *experimental*cli*features* | \
    *"manifest inspect"*"not supported"* | \
    *"manifest inspect"*unsupported* | \
    *"does not support"*"manifest inspect"*) return 0 ;;
    *) return 1 ;;
  esac
}

manifest_error=""
if manifest_error=$("$RUNTIME" manifest inspect "$ref" 2>&1); then
  verdict available
fi

# Auth takes precedence over every other phrase. Some registries include
# missing-resource wording in an authorization response; that still proves
# only that the caller could not authenticate.
is_auth_error "$manifest_error" && verdict unknown

if ! is_manifest_inspect_unsupported "$manifest_error"; then
  is_absent_error "$manifest_error" && verdict absent
  verdict unknown
fi

pull_error=""
if pull_error=$("$RUNTIME" pull -q "$ref" 2>&1); then
  verdict available
fi

is_auth_error "$pull_error" && verdict unknown
is_absent_error "$pull_error" && verdict absent
verdict unknown

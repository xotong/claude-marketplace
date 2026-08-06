#!/usr/bin/env bash
# =============================================================================
# Decide which scanner image actually runs, given the admin-configured image and
# the component template's image at the resolved (newest) component tag.
#
# Policy `follow-component` (default): adopt the TEMPLATE'S TAG while keeping the
# CONFIGURED REGISTRY AND PATH. The component is the authority on which analyzer
# version it was tested against; the admin config is the authority on where images
# are pulled from. Taking the template's ref wholesale would send an airgapped run
# to registry.gitlab.com, so only the tag crosses over:
#
#   configured  jfrog.internal/security/container-scanning:8
#   template    registry.gitlab.com/security-products/container-scanning:8.6.31
#   effective   jfrog.internal/security/container-scanning:8.6.31
#
# The adopted image is verified by pulling it. That pull is not overhead — it is
# the availability check AND it warms the cache the scan is about to use. If the
# mirror does not carry that tag yet, we say so and fall back to the configured
# image rather than failing the scan on a mirror gap.
#
# Policy `pinned`: always use the configured image. No pull, no adoption.
#
# Usage:  resolve-image.sh <configured_image> <template_image> [runtime] [policy]
# Prints: the effective image ref on stdout; diagnostics on stderr.
# =============================================================================
set -euo pipefail

CONFIGURED=${1:-}
TEMPLATE=${2:-}
RUNTIME=${3:-${RUNTIME:-docker}}
POLICY=${4:-${IMAGE_POLICY:-follow-component}}

# Without a configured image there is nothing to run and nothing to decide.
[ -n "$CONFIGURED" ] || { printf '%s\n' ""; exit 0; }

emit() { printf '%s\n' "$1"; }

if [ "$POLICY" != "follow-component" ]; then
  emit "$CONFIGURED"
  exit 0
fi

# Nothing to follow: the template declares no resolvable image (underivable
# variable, or no snapshot cached).
if [ -z "$TEMPLATE" ]; then
  emit "$CONFIGURED"
  exit 0
fi

# Split "registry/path/name:tag" into prefix ("registry/path"), name, and tag.
# A tag is only a tag if the last '/'-segment contains ':' — otherwise a port in
# the registry host (registry:5000/foo) would be mistaken for one.
split_tag() {
  local ref=$1 last
  last=${ref##*/}
  case "$last" in
    *:*) printf '%s\t%s\n' "${ref%:*}" "${ref##*:}" ;;
    *)   printf '%s\t%s\n' "$ref" "" ;;
  esac
}

configured_repo=$(split_tag "$CONFIGURED" | cut -f1)
configured_tag=$(split_tag "$CONFIGURED" | cut -f2)
template_tag=$(split_tag "$TEMPLATE" | cut -f2)

# An untagged template ref, or one that already matches, needs no work.
if [ -z "$template_tag" ] || [ "$template_tag" = "$configured_tag" ]; then
  emit "$CONFIGURED"
  exit 0
fi

candidate="${configured_repo}:${template_tag}"

echo "[image] component template declares ${template_tag}; configured ${configured_tag:-<untagged>}" >&2
echo "[image] trying ${candidate}" >&2

if "$RUNTIME" pull -q "$candidate" >/dev/null 2>&1; then
  echo "[image] using ${candidate} (component-tracked)" >&2
  emit "$candidate"
  exit 0
fi

echo "[image] WARNING: ${candidate} is not available from this registry." >&2
echo "[image]   The component moved to ${template_tag} but your mirror does not carry it yet." >&2
echo "[image]   Falling back to ${CONFIGURED}." >&2
echo "[image]   Ask your platform team to mirror ${configured_repo}:${template_tag}." >&2
emit "$CONFIGURED"

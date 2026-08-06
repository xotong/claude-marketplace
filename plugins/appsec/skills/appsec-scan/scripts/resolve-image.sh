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

emit() { printf '%s\n' "$1"; }

# No image: in config — the component is the sole source. This is the intended
# steady state when the catalogue's templates already name your internal
# registry: config carries component and version, nothing else.
if [ -z "$CONFIGURED" ]; then
  if [ -z "$TEMPLATE" ]; then
    # Fail loudly. Guessing a registry, or silently skipping the scanner, are
    # both worse than stopping: one runs an unknown image, the other reports a
    # clean scan for a category that never ran.
    echo "ERROR: cannot determine which image to run." >&2
    echo "  No image: is set for this category and the component template does not" >&2
    echo "  declare a resolvable image (it may build the ref from a variable this" >&2
    echo "  template never defines, or no snapshot was cached)." >&2
    echo "  Fix: set image: for this category in scanner-preferences.yaml, or" >&2
    echo "  re-vendor snapshots from an instance whose template declares one:" >&2
    echo "    bash scripts/revendor.sh <instance_url> [token_env]" >&2
    exit 2
  fi
  # Verify it the same way the configured path does. Without a configured image
  # there is nothing to fall back to, so an unavailable image is fatal here
  # rather than a warning — the alternative is a docker-run failure several
  # steps later with a far less useful message.
  if "$RUNTIME" pull -q "$TEMPLATE" >/dev/null 2>&1; then
    emit "$TEMPLATE"
    exit 0
  fi
  echo "ERROR: the component's image is not available from this registry." >&2
  echo "  Component declares: ${TEMPLATE}" >&2
  echo "  No image: is set for this category, so there is nothing to fall back to." >&2
  echo "  Fix (either one):" >&2
  echo "    - mirror ${TEMPLATE} into your registry, or" >&2
  echo "    - set image: for this category in scanner-preferences.yaml to pin a" >&2
  echo "      version you do carry (it also becomes the fallback for future bumps)." >&2
  exit 2
fi

if [ "$POLICY" != "follow-component" ]; then
  emit "$CONFIGURED"
  exit 0
fi

# Nothing to follow: the template declares no resolvable image (underivable
# variable, or no snapshot cached). The configured image stands on its own.
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

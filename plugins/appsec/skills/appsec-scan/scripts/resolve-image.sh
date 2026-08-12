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
# A tag may also carry a VARIANT after the version, which the admin owns for the
# same reason as the registry: it describes the target, not the analyzer release.
# Fortify's variant is the JDK the project compiles with, so adopting the tag
# whole would scan a Java 21 project with the component's default JDK 17 image:
#
#   configured  jfrog.internal/security/fortify-sca:25.2.0-jdk21-review
#   template    registry.gitlab.com/.../fortify-sca:25.2.1-jdk17-review
#   effective   jfrog.internal/security/fortify-sca:25.2.1-jdk21-review
#
# The adopted image is verified by pulling it. That pull is not overhead — it is
# the availability check AND it warms the cache the scan is about to use. If the
# mirror does not carry that tag yet, we say so and fall back to the configured
# image rather than failing the scan on a mirror gap.
#
# Policy `pinned`: always use the configured image. No pull, no adoption.
#
# Usage:  resolve-image.sh <configured_image> <template_image> [runtime] [policy]
#                          [pull_mode] [preferred_variant]
#         pull_mode is `pull` (default) or `no-pull` for dry-run resolution.
#         preferred_variant overrides the tag's variant suffix — the caller
#         detected what the project needs (see detect-java-release.sh). It beats
#         both the configured and the template variant, because it is evidence
#         from the codebase rather than a static guess. If the resulting image is
#         not available, resolution falls back rather than failing the scan.
# Prints: the effective image ref on stdout; diagnostics on stderr.
# =============================================================================
set -euo pipefail

CONFIGURED=${1:-}
TEMPLATE=${2:-}
RUNTIME=${3:-${RUNTIME:-docker}}
POLICY=${4:-${IMAGE_POLICY:-follow-component}}
PULL_MODE=${5:-pull}
PREFERRED_VARIANT=${6:-}

case "$PULL_MODE" in
  pull|no-pull) ;;
  *)
    echo "ERROR: unknown image pull mode: ${PULL_MODE}" >&2
    exit 2
    ;;
esac

emit() { printf '%s\n' "$1"; }

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

# Split "25.2.0-jdk21-review" into version "25.2.0" and variant "jdk21-review".
# A tag with no '-', or whose head is not version-shaped ("latest", "8"), has no
# variant and is returned whole with an empty second field.
split_variant() {
  local tag=$1 head
  case "$tag" in
    [0-9]*-*) head=${tag%%-*} ;;
    *) printf '%s\t\n' "$tag"; return ;;
  esac
  case "$head" in
    *[!0-9.]*) printf '%s\t\n' "$tag"; return ;;
  esac
  printf '%s\t%s\n' "$head" "${tag#*-}"
}

# Apply the caller's detected variant to the TEMPLATE ref up front, because the
# template supplies the tag on every downstream path — including the shipped
# state, where no image: is configured at all and the template ref is used whole.
# TEMPLATE_ORIGINAL is kept so an estate that mirrors only the component's default
# variant degrades to it instead of failing.
TEMPLATE_ORIGINAL=$TEMPLATE
if [ -n "$PREFERRED_VARIANT" ] && [ -n "$TEMPLATE" ]; then
  tmpl_pair=$(split_tag "$TEMPLATE")
  tmpl_repo=${tmpl_pair%%$'\t'*}
  tmpl_tag=${tmpl_pair#*$'\t'}
  tmpl_variant_pair=$(split_variant "$tmpl_tag")
  tmpl_version=${tmpl_variant_pair%%$'\t'*}
  tmpl_variant=${tmpl_variant_pair#*$'\t'}
  if [ -n "$tmpl_variant" ] && [ "$tmpl_variant" != "$PREFERRED_VARIANT" ]; then
    TEMPLATE="${tmpl_repo}:${tmpl_version}-${PREFERRED_VARIANT}"
    echo "[image] project needs ${PREFERRED_VARIANT}; component defaults to ${tmpl_variant}" >&2
  fi
fi

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
  if [ "$PULL_MODE" = no-pull ] || "$RUNTIME" pull -q "$TEMPLATE" >/dev/null 2>&1; then
    emit "$TEMPLATE"
    exit 0
  fi
  # A detected variant is a preference, not a requirement. If the estate mirrors
  # only the component's default variant, scan with that rather than not at all —
  # a wrong-JDK scan is worse than a right one, but far better than none.
  if [ "$TEMPLATE" != "$TEMPLATE_ORIGINAL" ]; then
    echo "[image] WARNING: ${TEMPLATE} is not available from this registry." >&2
    echo "[image]   Falling back to the component's default variant ${TEMPLATE_ORIGINAL}." >&2
    echo "[image]   The scan will use a JDK that does not match the project — ask your" >&2
    echo "[image]   platform team to mirror ${TEMPLATE}." >&2
    if [ "$PULL_MODE" = no-pull ] || "$RUNTIME" pull -q "$TEMPLATE_ORIGINAL" >/dev/null 2>&1; then
      emit "$TEMPLATE_ORIGINAL"
      exit 0
    fi
    TEMPLATE=$TEMPLATE_ORIGINAL
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

# Split the tab-separated pair in bash rather than with `cut`: coreutils is not
# guaranteed on a minimal airgapped host, and run-scan.sh treats a non-zero exit
# here as fatal -- a missing `cut` refused to scan at all instead of resolving
# an image.
configured_pair=$(split_tag "$CONFIGURED")
configured_repo=${configured_pair%%$'\t'*}
configured_tag=${configured_pair#*$'\t'}
template_pair=$(split_tag "$TEMPLATE")
template_tag=${template_pair#*$'\t'}

# An untagged template ref, or one that already matches, needs no work.
if [ -z "$template_tag" ] || [ "$template_tag" = "$configured_tag" ]; then
  emit "$CONFIGURED"
  exit 0
fi

# The variant is the admin's call, not the component's. A Fortify tag carries the
# JDK used to compile the target (25.2.0-jdk17-review vs -jdk21-review), so taking
# the template's tag wholesale silently downgrades a Java 21 project to a JDK 17
# analyzer -- the component's default overriding an explicit local choice. Extend
# the existing rule (component owns the VERSION, admin owns the rest) one field
# right: adopt the template's version, keep the configured variant.
#
# A PREFERRED_VARIANT outranks both and has already been folded into TEMPLATE
# above, so skip this block entirely when one was supplied: what the codebase
# demonstrably needs beats what someone typed into config months ago.
configured_variant_pair=$(split_variant "$configured_tag")
configured_variant=${configured_variant_pair#*$'\t'}
template_variant_pair=$(split_variant "$template_tag")
template_version=${template_variant_pair%%$'\t'*}
template_variant=${template_variant_pair#*$'\t'}

effective_tag=$template_tag
if [ -z "$PREFERRED_VARIANT" ] &&
   [ -n "$configured_variant" ] && [ -n "$template_variant" ] &&
   [ "$configured_variant" != "$template_variant" ]; then
  effective_tag="${template_version}-${configured_variant}"
  echo "[image] keeping configured variant ${configured_variant} (component declares ${template_variant})" >&2
  # Version matched too, so the configured ref already is the answer.
  if [ "$effective_tag" = "$configured_tag" ]; then
    emit "$CONFIGURED"
    exit 0
  fi
fi

candidate="${configured_repo}:${effective_tag}"

echo "[image] component template declares ${template_tag}; configured ${configured_tag:-<untagged>}" >&2
echo "[image] trying ${candidate}" >&2

if [ "$PULL_MODE" = no-pull ] || "$RUNTIME" pull -q "$candidate" >/dev/null 2>&1; then
  echo "[image] using ${candidate} (component-tracked)" >&2
  emit "$candidate"
  exit 0
fi

echo "[image] WARNING: ${candidate} is not available from this registry." >&2
echo "[image]   The component moved to ${template_tag} but your mirror does not carry it yet." >&2
echo "[image]   Falling back to ${CONFIGURED}." >&2
echo "[image]   Ask your platform team to mirror ${configured_repo}:${template_tag}." >&2
emit "$CONFIGURED"

#!/usr/bin/env bash
# =============================================================================
# Re-vendor the offline-fallback catalog snapshots from a live instance.
#
#   bash scripts/revendor.sh <instance_url> [token_env]
#
# e.g.  bash scripts/revendor.sh https://gitlab.com GITLAB_READ_TOKEN
#       bash scripts/revendor.sh https://gitlab.internal.company.com
#
# For every enabled component it resolves ~latest, copies template.yml,
# README.md and AGENTS.md into reference/catalog/<component>/<tag>/, stamps a
# provenance header, and regenerates scanners/<runner>.contract.
#
# SAFETY: a component that resolves [offline-fallback] is REFUSED, not vendored.
# Re-vendoring from the fallback would copy a snapshot onto itself and make a
# stale component look freshly confirmed — the same false-clean this skill
# exists to avoid. Fix the connection or the token and re-run.
#
# Prior tag directories are left in place; the resolver picks the highest.
# =============================================================================
set -euo pipefail

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SKILL_DIR="${SKILL_DIR:-$(dirname "$SCRIPTS_DIR")}"
SCANNERS_DIR="${SCANNERS_DIR:-$SKILL_DIR/scanners}"
REFERENCE_DIR="$SKILL_DIR/reference/catalog"

[ "$#" -ge 1 ] || {
  echo "ERROR: usage: revendor.sh <instance_url> [token_env]" >&2
  exit 2
}
INSTANCE=$1
TOKEN_ENV=${2:-}

if [ -z "${ENABLED_COMPONENTS+x}" ]; then
  eval "$(bash "$SCRIPTS_DIR/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml")"
fi

CACHE=$(mktemp -d)
trap 'rm -rf "$CACHE"' EXIT
TODAY=$(date +%F)
refused=0
vendored=0

for tuple in ${ENABLED_COMPONENTS:-}; do
  component="${tuple%%|*}"; rest="${tuple#*|}"
  rest="${rest#*|}"; runner="${rest%%|*}"

  resolved=$(bash "$SCRIPTS_DIR/catalog.sh" resolve \
    "$INSTANCE" "$component" '~latest' "$CACHE" "$TOKEN_ENV" 2>/dev/null) || {
    echo "REFUSED: $component — could not resolve at all" >&2
    refused=$((refused + 1))
    continue
  }

  case "$resolved" in
    *"[offline-fallback]"*)
      echo "REFUSED: $component — resolved from the vendored snapshot, not the instance." >&2
      echo "         Vendoring that would confirm a stale snapshot against itself." >&2
      refused=$((refused + 1))
      continue
      ;;
  esac

  tag=${resolved##*@}; tag=${tag%% *}
  src="$CACHE/$component/$tag"
  dst="$REFERENCE_DIR/$component/$tag"
  mkdir -p "$dst"

  cp "$src/template.yml" "$dst/template.yml"
  [ -f "$src/AGENTS.md" ] && cp "$src/AGENTS.md" "$dst/AGENTS.md"
  # The commit behind the tag, so a MOVED tag is detectable. fortify-sast 25.2.0
  # was re-tagged onto new content while this snapshot kept the old one, and
  # nothing could tell: same tag, same filenames, a different component.
  [ -f "$src/.commit" ] && cp "$src/.commit" "$dst/.commit"
  {
    printf '<!-- Vendored snapshot: fetched %s from %s CI/CD Catalog (component tag %s%s) -->\n' \
      "$TODAY" "$INSTANCE" "$tag" \
      "$([ -f "$src/.commit" ] && printf ', commit %s' "$(cut -c1-8 <"$src/.commit")")"
    cat "$src/README.md"
  } >"$dst/README.md"

  # Regenerate the contract, preserving its #-comment header.
  contract="$SCANNERS_DIR/${runner%.sh}.contract"
  if [ -f "$contract" ]; then
    {
      sed -n '/^#/p' "$contract"
      bash "$SCRIPTS_DIR/catalog.sh" contract "$component" "$CACHE" 2>/dev/null
    } >"$contract.new"
    mv "$contract.new" "$contract"
  fi

  echo "vendored: $component@$tag"
  vendored=$((vendored + 1))
done

echo
echo "$vendored vendored, $refused refused."
if [ "$refused" -gt 0 ]; then
  echo "Nothing was written for the refused components — their existing snapshots are untouched." >&2
  exit 1
fi
echo "Next:"
echo "  1. git diff — every changed line is a real upstream change. A new"
echo "     input.<name>.option= means the component gained a capability; check the"
echo "     runner has a matching arm (tests/test_catalog.py enforces this)."
echo "  2. Update '# Last synced' in any runner you reviewed against a new template."
echo "  3. python3 -m pytest $SKILL_DIR/tests/ -q"

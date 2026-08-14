#!/usr/bin/env bash
# =============================================================================
# Resolve every enabled catalog component and check it for drift.
#
# This exists as a script, not as a loop in SKILL.md, for one specific reason:
# the SKILL.md version iterated `for pair in $ENABLED_COMPONENTS`, which relies
# on the shell word-splitting an unquoted expansion. bash does; zsh does not.
# On a zsh host (the macOS default) that loop ran ONCE over the whole string —
# silently resolving 1 of 4 components and feeding the unparsed remainder into
# check-drift as an image argument, which produced a plausible-looking but
# entirely bogus DRIFT line. Wrong security output that looks right is worse
# than a crash, so the iteration lives here under a bash shebang where its
# behaviour is fixed.
#
# Also self-loads preferences when RUN_* vars are absent, so it does not depend
# on exports surviving between an agent's separate tool calls.
# =============================================================================
set -euo pipefail

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SKILL_DIR="${SKILL_DIR:-$(dirname "$SCRIPTS_DIR")}"
SCANNERS_DIR="${SCANNERS_DIR:-$SKILL_DIR/scanners}"

if [ -z "${ENABLED_COMPONENTS+x}" ]; then
  echo '[resolve-components] ENABLED_COMPONENTS absent, self-loading preferences...' >&2
  eval "$(bash "$SCRIPTS_DIR/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml")"
fi

CATALOG_CACHE="${CATALOG_CACHE:-.appsec-results/catalog}"
mkdir -p "$CATALOG_CACHE"

drift_lines=""
rows=""
count=0
config_error=false

# Word-splitting here is intentional and safe: this file is bash, and
# load-prefs.sh emits a space-separated list of tuples with no spaces inside.
for tuple in ${ENABLED_COMPONENTS:-}; do
  component="${tuple%%|*}"; rest="${tuple#*|}"
  version="${rest%%|*}"; rest="${rest#*|}"
  runner="${rest%%|*}"; image="${rest#*|}"
  count=$((count + 1))

  resolved=$(bash "$SCRIPTS_DIR/catalog.sh" resolve \
    "${GITLAB_INSTANCE:-}" "$component" "$version" "$CATALOG_CACHE" "${CATALOG_AUTH_ENV:-}") || {
    echo "ERROR: could not resolve $component" >&2
    continue
  }

  tag="${resolved##*@}"; tag="${tag%% *}"
  source_label="${resolved##*[}"; source_label="${source_label%]}"
  # A refused token is not an outage: continuing on the snapshot here would look
  # exactly like a live check that passed. catalog.sh already printed the
  # CONFIG-ERROR line; this makes the step itself fail so it cannot be scrolled past.
  case "$source_label" in
    *unauthorized*) config_error=true ;;
  esac

  if [ "$runner" != "none" ]; then
    component_drift=$(bash "$SCRIPTS_DIR/catalog.sh" check-drift \
      "$component" "$CATALOG_CACHE" "$SCANNERS_DIR/$runner" "$image") || true
  else
    component_drift=""
  fi

  if [ -n "$component_drift" ]; then
    drift_lines="${drift_lines}${component_drift}"$'\n'
    drift_cell="see below"
  else
    drift_cell="—"
  fi

  rows="${rows}| ${component} | ${tag} | ${source_label} | ${drift_cell} |"$'\n'
done

if [ "$count" -eq 0 ]; then
  echo "ERROR: no enabled components — check 'enabled:' in scanner-preferences.yaml" >&2
  exit 1
fi

echo "| Component | Version | Source | Drift |"
echo "|---|---|---|---|"
printf '%s' "$rows"

if [ -n "$drift_lines" ]; then
  echo
  printf '%s' "$drift_lines"
fi

# Printed the table first: the user still gets to see which components resolved
# and how. Then fail, so a refused token cannot be mistaken for a live check.
if [ "$config_error" = true ]; then
  echo "ERROR: at least one component resolved [offline-fallback: unauthorized] — fix the catalogue token before scanning. Do not work around it." >&2
  exit 1
fi

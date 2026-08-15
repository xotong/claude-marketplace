#!/usr/bin/env bash
# =============================================================================
# Tell a configuration failure apart from an environment failure.
#
# This is the one distinction the skill's error handling turns on:
#
#   configuration  the registry answered, and refused us. Only the admin can fix
#                  it, so retrying — or reaching for another image, registry,
#                  credential or endpoint — cannot succeed. It only hides the
#                  problem behind a scan that reads like a result. Terminal for
#                  whatever it blocks; see the CONFIG-ERROR: prefix in SKILL.md.
#   environment    we never got an answer: timeout, DNS, connection refused, 5xx.
#                  Falling back is legitimate here, and the airgap guarantee is
#                  built on it. Report the fallback, then continue.
#
# Sourced, never executed. Every caller is bash, because `nocasematch` is a bash
# builtin and registries differ on both spelling and capitalisation.
#
# Usage:  . "$SCRIPTS_DIR/classify-error.sh"
#         is_auth_error "$stderr_text" && ...
# =============================================================================

# Save and restore nocasematch around the match rather than setting it globally.
# Sourcing this must not silently change how the CALLER's own `case` statements
# match -- run-scan.sh alone branches on category names, container modes and
# runtime names, and none of those want case-insensitive matching.
is_auth_error() {
  _ca_saved=$(shopt -p nocasematch)
  shopt -s nocasematch
  case "$1" in
    *unauthorized* | \
    *"pull access denied"* | \
    *"denied: requested access"* | \
    *"requested access to the resource is denied"* | \
    *"no basic auth credentials"* | \
    *"authentication required"* | \
    *"401 unauthorized"* | \
    *"403 forbidden"*) _ca_rc=0 ;;
    *) _ca_rc=1 ;;
  esac
  eval "$_ca_saved"
  return "$_ca_rc"
}

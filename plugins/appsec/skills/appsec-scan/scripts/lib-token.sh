#!/usr/bin/env bash
# =============================================================================
# Resolve a GitLab API token without ever letting it touch argv, stdout,
# stderr, or a log line.
#
# Sourced, never executed:
#   . "$SCRIPTS_DIR/lib-token.sh"
#   appsec_resolve_token "$GITLAB_INSTANCE" "$CATALOG_AUTH_ENV"
#   # then read $APPSEC_RESOLVED_TOKEN / $APPSEC_TOKEN_SOURCE
#
# appsec_resolve_token <instance_url> <token_env_name> sets two globals; it
# prints nothing, on either stream, in either branch:
#   APPSEC_RESOLVED_TOKEN   the token value, or "" if none was found
#   APPSEC_TOKEN_SOURCE     env | glab | none
#
# Order:
#   1. The env var NAMED by token_env_name, if it is set and non-empty.
#   2. Otherwise, when settings.catalog.glab_fallback is true (exported as
#      CATALOG_GLAB_FALLBACK by load-prefs.sh) and `glab` is on PATH:
#      `glab config get token --host <host-of-instance_url>`. glab's own
#      stderr (a login hint when unauthenticated) is suppressed so it never
#      reaches a caller's captured diagnostics.
#   3. Otherwise APPSEC_TOKEN_SOURCE=none and APPSEC_RESOLVED_TOKEN="".
#
# The token is captured straight from command substitution into a variable —
# it is never echoed, never interpolated into another command's argv (which
# would leak it into `ps`), and never written to a file. Only the resolved
# HOST (never the token) is passed as an argv value, to glab itself.
#
# bash 3.2 (macOS /bin/bash) note: this deliberately uses `eval` for indirect
# variable expansion instead of ${!name}, which behaves inconsistently across
# the bash versions this skill has to run under; the same idiom is already
# used in run-scan.sh's validate_env().
# =============================================================================

appsec_host_of() {
  # Strip scheme and any path; keep a non-default port, since glab's --host
  # stores exactly what was used at `glab auth login` and a self-hosted
  # instance on a non-standard port would otherwise never match.
  local url host
  url=${1:-}
  host=${url#*://}
  host=${host%%/*}
  printf '%s' "$host"
}

appsec_resolve_token() {
  local instance_url token_env_name host

  instance_url=${1:-}
  token_env_name=${2:-}

  APPSEC_RESOLVED_TOKEN=
  APPSEC_TOKEN_SOURCE=none

  if [ -n "$token_env_name" ]; then
    eval "APPSEC_RESOLVED_TOKEN=\${$token_env_name:-}"
    if [ -n "$APPSEC_RESOLVED_TOKEN" ]; then
      APPSEC_TOKEN_SOURCE=env
      return 0
    fi
    APPSEC_RESOLVED_TOKEN=
  fi

  if [ "${CATALOG_GLAB_FALLBACK:-false}" = true ] && command -v glab >/dev/null 2>&1; then
    host=$(appsec_host_of "$instance_url")
    if [ -n "$host" ]; then
      if APPSEC_RESOLVED_TOKEN=$(glab config get token --host "$host" 2>/dev/null) && \
         [ -n "$APPSEC_RESOLVED_TOKEN" ]; then
        APPSEC_TOKEN_SOURCE=glab
        return 0
      fi
      APPSEC_RESOLVED_TOKEN=
    fi
  fi

  APPSEC_TOKEN_SOURCE=none
  return 0
}

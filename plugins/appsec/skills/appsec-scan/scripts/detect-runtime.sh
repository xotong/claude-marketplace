#!/usr/bin/env bash
set -euo pipefail

# Usage: detect-runtime.sh [--require-daemon]
#
# Without --require-daemon this only reports which runtime BINARY is available,
# which is all --dry-run needs. With it, the daemon must actually answer.
#
# The distinction matters: `command -v docker` succeeds while Docker Desktop is
# wedged or still starting, so preflight used to report a healthy environment
# and the real failure surfaced much later as a hanging `docker pull`. Preflight
# passes --require-daemon so the gate means what SKILL.md says it means.

require_daemon=false
if [ "${1:-}" = "--require-daemon" ]; then
  require_daemon=true
  shift
fi

# `docker info` blocks indefinitely against a present-but-dead socket, and macOS
# has no timeout(1). Bound it the way run-scan.sh bounds scanners: background the
# probe and poll with kill -0.
daemon_alive() {
  local rt probe_pid ticks limit
  rt=$1
  limit=${APPSEC_RUNTIME_PROBE_TIMEOUT:-10}
  case "$limit" in ''|*[!0-9]*) limit=10 ;; esac

  "$rt" info >/dev/null 2>&1 &
  probe_pid=$!
  ticks=0
  while kill -0 "$probe_pid" 2>/dev/null; do
    if [ "$ticks" -ge $((limit * 4)) ]; then
      kill -9 "$probe_pid" 2>/dev/null || true
      wait "$probe_pid" 2>/dev/null || true
      return 1
    fi
    sleep 0.25
    ticks=$((ticks + 1))
  done
  wait "$probe_pid" 2>/dev/null
}

emit() {
  local rt=$1
  if [ "$require_daemon" = true ] && ! daemon_alive "$rt"; then
    echo "ERROR: $rt is installed but its daemon is not responding. Start it (e.g. open Docker Desktop, or 'podman machine start') and retry." >&2
    return 1
  fi
  echo "$rt"
}

runtime="${CONTAINER_RUNTIME:-auto}"

case "$runtime" in
  auto)
    if command -v docker >/dev/null 2>&1 && emit docker 2>/dev/null; then
      :
    elif command -v podman >/dev/null 2>&1 && emit podman 2>/dev/null; then
      :
    elif command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1; then
      # A binary exists but no daemon answered — report that, not "not found".
      echo "ERROR: a container runtime is installed but no daemon is responding. Start Docker Desktop or 'podman machine start' and retry." >&2
      exit 1
    else
      echo "ERROR: no container runtime found (need docker or podman)" >&2
      exit 1
    fi
    ;;
  docker|podman)
    command -v "$runtime" >/dev/null 2>&1 || {
      echo "ERROR: $runtime runtime not found" >&2
      exit 1
    }
    emit "$runtime"
    ;;
  *)
    echo "ERROR: unsupported CONTAINER_RUNTIME '$runtime' (expected auto, docker, or podman)" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
set -euo pipefail

runtime="${CONTAINER_RUNTIME:-auto}"

case "$runtime" in
  auto)
    if command -v docker >/dev/null 2>&1; then
      echo "docker"
    elif command -v podman >/dev/null 2>&1; then
      echo "podman"
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
    echo "$runtime"
    ;;
  *)
    echo "ERROR: unsupported CONTAINER_RUNTIME '$runtime' (expected auto, docker, or podman)" >&2
    exit 1
    ;;
esac

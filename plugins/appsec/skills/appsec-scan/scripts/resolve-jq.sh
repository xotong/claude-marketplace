#!/usr/bin/env bash
set -euo pipefail

if jq_path="$(command -v jq 2>/dev/null)"; then
  echo "$jq_path"
  exit 0
fi

if [ -z "${JQ_INSTALL_URL:-}" ]; then
  echo "INFO: jq not found and JQ_INSTALL_URL unset; severity summary will show UNKNOWN" >&2
  exit 0
fi

command -v curl >/dev/null 2>&1 || {
  echo "WARNING: curl not found; unable to download jq" >&2
  exit 0
}

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$arch" in
  x86_64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
esac

cache_dir="${APPSEC_RESULTS_DIR:-.appsec-results}"
mkdir -p "$cache_dir/bin"
jq_path="$(cd "$cache_dir/bin" && pwd)/jq"
url="${JQ_INSTALL_URL//\{os\}/$os}"
url="${url//\{arch\}/$arch}"

if ! curl -fsSL "$url" -o "$jq_path" || ! chmod +x "$jq_path"; then
  echo "WARNING: failed to download jq from $url" >&2
  exit 0
fi

"$jq_path" --version >/dev/null 2>&1 || {
  echo "WARNING: downloaded jq is not executable" >&2
  exit 0
}

echo "$jq_path"

#!/usr/bin/env bash
set -euo pipefail

if python_path="$(command -v python3 2>/dev/null)" && \
   "$python_path" -c "import sys" >/dev/null 2>&1; then
  echo "$python_path"
  exit 0
fi

if [ -z "${PYTHON_INSTALL_URL:-}" ]; then
  echo "INFO: python3 not found and PYTHON_INSTALL_URL unset; using legacy UNKNOWN summary" >&2
  exit 0
fi

command -v curl >/dev/null 2>&1 || {
  echo "WARNING: curl not found; unable to download python3" >&2
  exit 0
}
command -v tar >/dev/null 2>&1 || {
  echo "WARNING: tar not found; unable to extract python3" >&2
  exit 0
}

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$arch" in
  x86_64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
esac

cache_dir="${APPSEC_RESULTS_DIR:-.appsec-results}"
mkdir -p "$cache_dir/bin" || {
  echo "WARNING: cannot create $cache_dir/bin; using legacy UNKNOWN summary" >&2
  exit 0
}
bin_dir="$(cd "$cache_dir/bin" && pwd)"
archive_path="$bin_dir/python.tar.gz"
url="${PYTHON_INSTALL_URL//\{os\}/$os}"
url="${url//\{arch\}/$arch}"

# ponytail: no checksum verification yet; add settings.python.sha256 as the upgrade path
if ! curl -fsSL --max-time 30 "$url" -o "$archive_path" || \
   ! tar -xzf "$archive_path" -C "$bin_dir"; then
  echo "WARNING: failed to download or extract python3 from $url" >&2
  rm -f "$archive_path"
  exit 0
fi
rm -f "$archive_path"

python_path=
if [ -x "$bin_dir/python3" ]; then
  python_path="$bin_dir/python3"
else
  python_path="$(find "$bin_dir" -type f -name python3 -perm -u+x 2>/dev/null | sed -n '1p')"
fi

if [ -z "$python_path" ] || ! "$python_path" -c "import sys" >/dev/null 2>&1; then
  echo "WARNING: downloaded python3 is not executable" >&2
  exit 0
fi

echo "$python_path"

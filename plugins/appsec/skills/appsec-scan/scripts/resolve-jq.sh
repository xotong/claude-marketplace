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
mkdir -p "$cache_dir/bin" || {
  echo "WARNING: cannot create $cache_dir/bin; severity summary will show UNKNOWN" >&2
  exit 0
}
jq_path="$(cd "$cache_dir/bin" && pwd)/jq"
# {jq_os} follows jq's own release asset names (jq-macos-arm64, jq-linux-amd64);
# {os} stays uname's spelling for internal mirrors laid out that way.
jq_os=$os
[ "$os" = darwin ] && jq_os=macos
url="${JQ_INSTALL_URL//\{os\}/$os}"
url="${url//\{jq_os\}/$jq_os}"
url="${url//\{arch\}/$arch}"

# ponytail: no checksum verification — internal TLS registry is the trust boundary; add settings.jq.sha256 if that changes
if ! curl -fsSL --max-time 30 "$url" -o "$jq_path" || ! chmod +x "$jq_path"; then
  echo "WARNING: failed to download jq from $url" >&2
  exit 0
fi

# Official jq releases publish sha256sum.txt beside the assets. Verify against it when it
# exists; a github.com download that cannot be verified is never executed.
sums_url="${url%/*}/sha256sum.txt"
asset="${url##*/}"
if want=$(curl -fsSL --max-time 30 "$sums_url" 2>/dev/null | awk -v a="$asset" '$2 == a || $2 == "*" a { print $1 }') && [ -n "$want" ]; then
  got=$({ shasum -a 256 "$jq_path" 2>/dev/null || sha256sum "$jq_path"; } | awk '{ print $1 }')
  if [ "$got" != "$want" ]; then
    echo "WARNING: jq from $url does not match its published sha256; not using it" >&2
    rm -f "$jq_path"
    exit 0
  fi
elif [ "${url#https://github.com/}" != "$url" ]; then
  echo "WARNING: could not verify jq from $url against $sums_url; not using it" >&2
  rm -f "$jq_path"
  exit 0
fi
"$jq_path" --version >/dev/null 2>&1 || {
  echo "WARNING: downloaded jq is not executable" >&2
  exit 0
}

echo "$jq_path"

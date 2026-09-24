#!/usr/bin/env bash
# =============================================================================
# Discover every Dockerfile-like build file in a repo, one per line:
#   <repo-relative path>\t<build context dir, repo-relative>\t<slug>
#
# run-scan.sh's find_dockerfile() (scripts/run-scan.sh) only ever surfaces a
# single Dockerfile: an explicit $DOCKERFILE, ./Dockerfile, or the first hit
# of a shallow find — enough for a single-service repo, but a monorepo with a
# Dockerfile per service needs every one of them enumerated up front so a
# later phase can scan them all. This script only discovers; it does not
# choose a scan target or build anything.
#
# Matches (case-insensitive basename): Dockerfile, Dockerfile.<suffix>,
# <prefix>.Dockerfile, Containerfile, Containerfile.<suffix>. Deliberately
# NOT matched: <prefix>.Containerfile — it is not part of the spec this pins.
#
# File set: scripts/lib-files.sh's appsec_list_repo_files() + appsec_is_excluded_path()
# (shared with remote-match.sh) — inside a git work tree, `git ls-files
# --cached --others --exclude-standard` (tracked + untracked-but-not-ignored,
# so a .gitignore'd Dockerfile is excluded, while an untracked-but-not-ignored
# one is kept); outside git, `find`. Both modes drop a fixed list of path
# segments that are never ours to scan: see APPSEC_EXCLUDE_SEGMENTS in
# lib-files.sh (.git, node_modules, vendor, .appsec-results, .venv, venv,
# __pycache__, .terraform, .tox, target, dist, .gradle).
#
# Build context is always the Dockerfile's own directory ("." for the repo
# root) — a later phase may let users override that per-Dockerfile.
#
# The slug is the lowercased path with every run of characters outside
# [a-z0-9] collapsed to one '-', trimmed of leading/trailing '-'. Collisions
# (distinct paths that slugify the same way) are disambiguated in
# sorted-path order with -2, -3, ... suffixes.
#
# bash 3.2 (macOS stock /bin/bash) compatible: no associative arrays, no
# mapfile, no ${var,,}. Element expansion ("${arr[@]}") on an empty array
# throws "unbound variable" under `set -u` in 3.2, so every such expansion
# below happens only once the array is known to be non-empty (the early
# `exit 0` on an empty PATHS guarantees that for everything after it).
#
# Usage:  detect-dockerfiles.sh [project_root]     (default: $PWD)
# Output: zero or more TAB-separated lines, sorted by path (LC_ALL=C).
# Exit:   0 whenever project_root exists (zero lines means none found),
#         2 on a usage error or a missing/non-directory root.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib-files.sh
. "$SCRIPT_DIR/lib-files.sh"

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [project_root]" >&2
  exit 2
fi

ROOT=${1:-$PWD}

if [ ! -d "$ROOT" ]; then
  echo "detect-dockerfiles.sh: no such directory: $ROOT" >&2
  exit 2
fi

is_dockerfile_name() {
  # $1 = basename; matches the case-insensitive patterns in the header.
  local lower
  lower=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    dockerfile|dockerfile.*|*.dockerfile|containerfile|containerfile.*) return 0 ;;
    *) return 1 ;;
  esac
}

PATHS=()

collect() {
  # $1 = path relative to ROOT, no leading ./
  case "$1" in
    *$'\t'*|*$'\n'*)
      echo "detect-dockerfiles.sh: skipping path with TAB/newline: $1" >&2
      return 0
      ;;
  esac
  appsec_is_excluded_path "$1" && return 0
  is_dockerfile_name "$(basename "$1")" || return 0
  PATHS+=("$1")
}

while IFS= read -r -d '' relpath; do
  collect "$relpath"
done < <(appsec_list_repo_files "$ROOT")

if [ "${#PATHS[@]}" -eq 0 ]; then
  exit 0
fi

SORTED=()
while IFS= read -r p; do
  SORTED+=("$p")
done < <(printf '%s\n' "${PATHS[@]}" | LC_ALL=C sort)

# Base slug -> occurrence count so far, as parallel arrays (bash 3.2 has no
# associative arrays). First occurrence of a slug keeps it bare; later ones
# get -2, -3, ... in the sorted-path order already established above.
SEEN_SLUGS=()
SEEN_COUNTS=()

for p in "${SORTED[@]}"; do
  base_slug=$(appsec_slugify "$p")
  count=0
  for i in "${!SEEN_SLUGS[@]}"; do
    if [ "${SEEN_SLUGS[$i]}" = "$base_slug" ]; then
      count=$(( SEEN_COUNTS[i] + 1 ))
      SEEN_COUNTS[i]=$count
      break
    fi
  done
  if [ "$count" -eq 0 ]; then
    SEEN_SLUGS+=("$base_slug")
    SEEN_COUNTS+=(1)
    slug=$base_slug
  else
    slug="${base_slug}-${count}"
  fi

  ctx=$(dirname "$p")

  printf '%s\t%s\t%s\n' "$p" "$ctx" "$slug"
done

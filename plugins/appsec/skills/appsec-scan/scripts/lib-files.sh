#!/usr/bin/env bash
# =============================================================================
# Shared repo-file discovery and slug helpers for appsec-scan's scripts.
# Sourced, never executed: . "$SCRIPTS_DIR/lib-files.sh"
#
#   appsec_list_repo_files <root>   NUL-separated paths under <root>, no
#                                    leading "./", NOT exclude-filtered (each
#                                    caller applies appsec_is_excluded_path
#                                    itself, alongside its own extra rules).
#   appsec_is_excluded_path <path>  0 if <path> is under an excluded segment.
#   appsec_slugify <string>         lowercased, [^a-z0-9]+ -> "-", trimmed.
#
# bash 3.2 (macOS stock /bin/bash) compatible.
# =============================================================================

APPSEC_EXCLUDE_SEGMENTS=(.git node_modules vendor .appsec-results .venv venv __pycache__ .terraform .tox target dist .gradle)

appsec_is_excluded_path() {
  local wrapped seg
  wrapped="/$1/"
  for seg in "${APPSEC_EXCLUDE_SEGMENTS[@]}"; do
    case "$wrapped" in
      */"$seg"/*) return 0 ;;
    esac
  done
  return 1
}

appsec_list_repo_files() {
  local root=$1
  if command -v git >/dev/null 2>&1 && (cd "$root" && git rev-parse --is-inside-work-tree >/dev/null 2>&1); then
    (cd "$root" && git ls-files -z --cached --others --exclude-standard)
  else
    (cd "$root" && find . \
      \( -name .git -o -name node_modules -o -name vendor -o -name .appsec-results \
         -o -name .venv -o -name venv -o -name __pycache__ -o -name .terraform \
         -o -name .tox -o -name target -o -name dist -o -name .gradle \) -prune -o -type f -print0) |
    while IFS= read -r -d '' relpath; do
      printf '%s\0' "${relpath#./}"
    done
  fi
}

appsec_slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

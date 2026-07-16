#!/usr/bin/env bash
set -euo pipefail

RESULTS_DIR="${APPSEC_RESULTS_DIR:-.appsec-results}"
STATE_FILE="$RESULTS_DIR/loop-state"

error() { printf 'ERROR: %s\n' "$*" >&2; }
warning() { printf 'WARNING: %s\n' "$*" >&2; }

write_state() {
  mkdir -p "$RESULTS_DIR"
  printf '{"iteration":%s,"last_total":%s}\n' "$1" "$2" > "$STATE_FILE"
}

read_iteration() {
  [ -f "$STATE_FILE" ] || { printf '%s\n' 1; return; }
  sed -n 's/.*"iteration"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$STATE_FILE" | sed -n '1p'
}

case "${1:-}" in
  --init)
    status="$(git status --porcelain 2>/dev/null)" || {
      error "not inside a Git worktree"
      exit 1
    }
    if printf '%s\n' "$status" | awk 'NF && substr($0,1,2) != "??" { found=1 } END { exit !found }'; then
      error "tracked changes must be committed or stashed before creating a fix branch"
      exit 1
    fi
    if printf '%s\n' "$status" | awk 'substr($0,1,2) == "??" { found=1 } END { exit !found }'; then
      warning "untracked files will remain in the worktree"
    fi
    branch="appsec/fix-$(date +%Y%m%d)-$(git rev-parse --short HEAD)"
    if git show-ref --verify --quiet "refs/heads/$branch"; then
      git checkout "$branch" >/dev/null
    else
      git checkout -b "$branch" >/dev/null
    fi
    total=-1
    if [ -f "$RESULTS_DIR/findings.triaged.json" ]; then
      parsed="$(sed -n 's/.*"total"[[:space:]]*:[[:space:]]*\(-\{0,1\}[0-9][0-9]*\).*/\1/p' "$RESULTS_DIR/findings.triaged.json" | sed -n '1p')"
      if [ -z "$parsed" ]; then
        parsed="$(awk '{ line=$0; while (match(line, /"fingerprint"[[:space:]]*:/)) { count++; line=substr(line, RSTART+RLENGTH) } } END { print count+0 }' "$RESULTS_DIR/findings.triaged.json")"
      fi
      [ -z "$parsed" ] || total=$parsed
    fi
    write_state 1 "$total"
    printf '%s\n' "$branch"
    ;;
  --check-progress)
    [ "$#" -eq 3 ] || { error "usage: fix-branch.sh --check-progress <prev_total> <curr_total>"; exit 2; }
    iteration="$(read_iteration)"
    [ -n "$iteration" ] || iteration=1
    iteration=$((iteration + 1))
    write_state "$iteration" "$3"
    if [ "$iteration" -gt 5 ]; then
      error "fix loop exceeded 5 iterations"
      exit 1
    fi
    if [ "$3" -ge "$2" ]; then
      error "no progress: current total $3 is not below previous total $2"
      exit 1
    fi
    ;;
  --status)
    [ -f "$STATE_FILE" ] || { error "loop state not found: $STATE_FILE"; exit 1; }
    sed -n '1p' "$STATE_FILE"
    ;;
  *)
    error "usage: fix-branch.sh --init | --check-progress <prev_total> <curr_total> | --status"
    exit 2
    ;;
esac

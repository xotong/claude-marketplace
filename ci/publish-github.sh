#!/usr/bin/env bash
# Publish this repo's main to the public GitHub mirror, one way, with the internal
# domain scrubbed from every text file. This repo is the source of truth;
# never merge GitHub back into it.
#
#   bash ci/publish-github.sh <internal-domain> <source-ref> [github-remote]
#   e.g. bash ci/publish-github.sh apps.example.internal internal/main origin
#
# The domain is an argument on purpose: this script is itself published, so it must not
# contain the name it scrubs. Every host under that domain becomes gitlab.example.com
# (the only internal host the repo names).
set -euo pipefail

DOMAIN=${1:?usage: publish-github.sh <internal-domain> <source-ref> [github-remote]}
SRC=${2:?usage: publish-github.sh <internal-domain> <source-ref> [github-remote]}
DST=${3:-origin}

git fetch -q "$DST" main

# Paths that exist only on the public mirror (see github/ONLY.txt on the
# destination's current main) never appear in the source tree, so read the
# list before that tree gets replaced below. No such file -> nothing to
# carry forward, same as before this list existed.
only_list=$(git show "$DST/main:github/ONLY.txt" 2>/dev/null || true)
GITHUB_ONLY=()
while IFS= read -r p; do
  case "$p" in ''|'#'*) continue ;; esac
  GITHUB_ONLY+=("${p%/}")
done <<<"$only_list"

tmp=$(mktemp -d)
trap 'git worktree remove --force "$tmp" >/dev/null 2>&1 || true' EXIT
git worktree add -q --detach "$tmp" "$DST/main"

# Replace the tree wholesale with the source tree (deletions included).
git -C "$tmp" rm -rq --ignore-unmatch .
git archive "$SRC" | tar -x -C "$tmp"

# Fail closed: a path that is supposed to exist only on the public mirror must
# not also show up in the source tree -- that's a conflict for a human to
# resolve, not something to silently overwrite either way.
for p in "${GITHUB_ONLY[@]:-}"; do
  [ -n "$p" ] || continue
  if [ -e "$tmp/$p" ]; then
    echo "publish-github: $p is supposed to be GitHub-only but is also in $SRC; nothing pushed" >&2
    exit 1
  fi
done

# Restore each GitHub-only path from the destination's current main so it
# survives this sync even though the source tree never has it.
for p in "${GITHUB_ONLY[@]:-}"; do
  [ -n "$p" ] || continue
  git -C "$tmp" checkout "$DST/main" -- "$p"
done

# Internal-only plugins: their license forbids making them available to any
# third party (see VENDORED.md), so they never leave this org. Strip them and
# every reference to them out of the export before anything else runs.
INTERNAL_ONLY=("claude-security")

for p in "${INTERNAL_ONLY[@]}"; do
  rm -rf "$tmp/plugins/$p"
done

# Drop the internal-only entries from the marketplace listing and from any
# plugin's `dependencies` array (so a future bundle, e.g. essentials, can't
# pull one back in through that path).
python3 - "$tmp" "${INTERNAL_ONLY[@]}" <<'PYEOF'
import json, sys, pathlib

tmp = pathlib.Path(sys.argv[1])
internal_only = set(sys.argv[2:])

mp_path = tmp / ".claude-plugin" / "marketplace.json"
mp = json.loads(mp_path.read_text())
mp["plugins"] = [p for p in mp["plugins"] if p.get("name") not in internal_only]
mp_path.write_text(json.dumps(mp, indent=2) + "\n")

for pj_path in tmp.glob("plugins/**/.claude-plugin/plugin.json"):
    pj = json.loads(pj_path.read_text())
    deps = pj.get("dependencies")
    if deps and any(d in internal_only for d in deps):
        pj["dependencies"] = [d for d in deps if d not in internal_only]
        pj_path.write_text(json.dumps(pj, indent=2) + "\n")
PYEOF

# Fail closed: an internal-only plugin directory must not survive into the export.
for p in "${INTERNAL_ONLY[@]}"; do
  if [ -e "$tmp/plugins/$p" ]; then
    echo "publish-github: $p is internal-only and still present in the export; nothing pushed" >&2
    exit 1
  fi
done

# Marketplace entries for the GitHub-only paths just restored above: carry
# forward any entry from the destination's marketplace whose `source` lives
# under one of those paths and that the source's own marketplace doesn't
# already list (it wouldn't, since the source tree never has that path).
python3 - "$tmp" "$DST" <<'PYEOF'
import json, pathlib, subprocess, sys

tmp = pathlib.Path(sys.argv[1])
dst = sys.argv[2]

only_path = tmp / "github" / "ONLY.txt"
github_only = []
if only_path.exists():
    for line in only_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            github_only.append(line.rstrip("/"))

def under_github_only(source):
    s = source[2:] if source.startswith("./") else source
    return any(s == p or s.startswith(p + "/") for p in github_only)

mp_path = tmp / ".claude-plugin" / "marketplace.json"
mp = json.loads(mp_path.read_text())
existing_names = {p.get("name") for p in mp["plugins"]}

try:
    raw = subprocess.run(
        ["git", "show", f"{dst}/main:.claude-plugin/marketplace.json"],
        capture_output=True, text=True, check=True,
    ).stdout
    dst_plugins = json.loads(raw).get("plugins", [])
except subprocess.CalledProcessError:
    dst_plugins = []

for p in dst_plugins:
    if p.get("name") not in existing_names and under_github_only(p.get("source", "")):
        mp["plugins"].append(p)

mp_path.write_text(json.dumps(mp, indent=2) + "\n")
PYEOF

# GitHub-only README content, if the restore above brought any back.
if [ -f "$tmp/github/README-extra.md" ]; then
  { printf '\n---\n\n'; cat "$tmp/github/README-extra.md"; } >>"$tmp/README.md"
fi

d=$(printf '%s' "$DOMAIN" | sed 's/[.]/\\./g')
grep -rlIi --exclude-dir=.git -e "$d" "$tmp" | while IFS= read -r f; do
  perl -pi -e "s/([a-z0-9-]+\\.)*$d/gitlab.example.com/gi" "$f"
done || true  # grep finds nothing -> exit 1 under pipefail; the check below still fails closed

# Fail closed: nothing may still mention the domain, text or binary.
if grep -rlai --exclude-dir=.git -e "$d" "$tmp"; then
  echo "publish-github: the files above still contain the internal domain; nothing pushed" >&2
  exit 1
fi

git -C "$tmp" add -A
if git -C "$tmp" diff --cached --quiet; then
  echo "publish-github: GitHub main already matches $SRC"
  exit 0
fi
git -C "$tmp" commit -q -m "Sync from internal main ($(git rev-parse --short "$SRC")), internal hostnames scrubbed"
git -C "$tmp" push -q "$DST" HEAD:main
echo "publish-github: pushed $(git -C "$tmp" rev-parse --short HEAD) to $DST/main"

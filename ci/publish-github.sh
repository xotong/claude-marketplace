#!/usr/bin/env bash
# Publish the self-hosted main to the public GitHub mirror, one way, with the internal
# domain scrubbed from every text file. The self-hosted GitLab is the source of truth;
# never merge GitHub back into it.
#
#   bash ci/publish-github.sh <internal-domain> [source-ref] [github-remote]
#   e.g. bash ci/publish-github.sh apps.example.internal selfhosted/main origin
#
# The domain is an argument on purpose: this script is itself published, so it must not
# contain the name it scrubs. Every host under that domain becomes gitlab.example.com
# (the only internal host the repo names).
set -euo pipefail

DOMAIN=${1:?usage: publish-github.sh <internal-domain> [source-ref] [github-remote]}
SRC=${2:-selfhosted/main}
DST=${3:-origin}

git fetch -q "$DST" main
tmp=$(mktemp -d)
trap 'git worktree remove --force "$tmp" >/dev/null 2>&1 || true' EXIT
git worktree add -q --detach "$tmp" "$DST/main"

# Replace the tree wholesale with the source tree (deletions included).
git -C "$tmp" rm -rq --ignore-unmatch .
git archive "$SRC" | tar -x -C "$tmp"

d=$(printf '%s' "$DOMAIN" | sed 's/[.]/\\./g')
grep -rlIi --exclude-dir=.git -e "$d" "$tmp" | while IFS= read -r f; do
  perl -pi -e "s/([a-z0-9-]+\\.)*$d/gitlab.example.com/gi" "$f"
done

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
git -C "$tmp" commit -q -m "Sync from self-hosted main ($(git rev-parse --short "$SRC")), internal hostnames scrubbed"
git -C "$tmp" push -q "$DST" HEAD:main
echo "publish-github: pushed $(git -C "$tmp" rev-parse --short HEAD) to $DST/main"

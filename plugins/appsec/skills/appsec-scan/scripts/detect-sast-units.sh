#!/bin/sh
# =============================================================================
# Discover every unit Fortify should scan, one per line: <path>|<language>
#
# Fortify is a per-build-tree scanner: CI includes the component once per
# service, each with its own source-path, and gets one scan each. Locally there
# are no includes to read, so the units have to be discovered — and until they
# were, run-scan.sh detected ONE language from the repo root and scanned ONE
# path. On a repo with a root manifest plus services in subdirectories that
# scanned the root and silently ignored the rest, while the coverage record
# still reported sast as covered. A category that ran is not the same as a
# repository that was scanned.
#
# Dependency scanning needs none of this: its analyzer walks the whole worktree
# in one pass, which is why only SAST fans out.
#
# Pruning rule: a directory does not produce a unit for a language when an
# ANCESTOR directory already produced one for that same language. That is what
# keeps a Gradle multi-module build (root `build.gradle` plus a `build.gradle`
# per module) or an npm workspace from exploding into one scan per module, while
# still finding a Python service that sits beside a JavaScript one.
#
# ponytail: ancestor-pruning is a heuristic, and it under-scans one shape — a
# root manifest that exists only for tooling, with the real projects below it
# (root package.json for linting + services/*/package.json). The unit list is
# printed before scanning and FORTIFY_LANGUAGE/SOURCE_PATH still pin a single
# unit, so that ceiling is visible and overridable rather than silent. Upgrade
# path if it bites: read the workspace/module declarations (settings.gradle,
# package.json workspaces, go.work) instead of guessing from the tree shape.
#
# Usage: detect-sast-units.sh [root_dir]
# Output: zero or more "<path>|<language>" lines; "." is the repo root.
#         Empty output means nothing recognisable was found — the caller must
#         treat that as "SAST did not run", never as "nothing to find".
# =============================================================================
set -eu

ROOT=${1:-.}
# Bounded so a deep monorepo does not walk forever. Four levels covers the
# common services/<name>/<project> layout with one to spare.
MAXDEPTH=${APPSEC_SAST_DISCOVERY_DEPTH:-4}

cd "$ROOT" 2>/dev/null || exit 0

# Directories that hold dependencies or build output, never source we own. A
# node_modules with 400 package.json files would otherwise become 400 units.
find . -maxdepth "$MAXDEPTH" \
  -type d \( -name .git -o -name node_modules -o -name vendor -o -name .venv \
             -o -name venv -o -name target -o -name dist -o -name .gradle \
             -o -name __pycache__ -o -name .appsec-results \) -prune -o \
  -type f \( -name pom.xml -o -name build.gradle -o -name build.gradle.kts \
             -o -name requirements.txt -o -name pyproject.toml \
             -o -name package.json -o -name go.mod \) -print 2>/dev/null |
awk '
{
  path = $0
  sub(/^\.\//, "", path)
  n = split(path, parts, "/")
  file = parts[n]
  if (n == 1) {
    dir = "."
  } else {
    dir = parts[1]
    for (i = 2; i < n; i++) dir = dir "/" parts[i]
  }

  lang = ""
  if (file == "build.gradle" || file == "build.gradle.kts") lang = "gradle"
  else if (file == "pom.xml")                               lang = "maven"
  else if (file == "requirements.txt" || file == "pyproject.toml") lang = "python"
  else if (file == "package.json")                          lang = "javascript"
  else if (file == "go.mod")                                lang = "go"
  if (lang == "") next

  key = dir "|" lang
  if (key in seen) next
  seen[key] = 1
  dirs[++count] = dir
  langs[count] = lang
}
END {
  for (i = 1; i <= count; i++) {
    # Same precedence run-scan.sh always applied at the root: a Gradle build in
    # a directory owns it, so its pom.xml is part of that build, not a unit.
    if (langs[i] == "maven" && ((dirs[i] "|gradle") in seen)) continue

    keep = 1
    for (j = 1; j <= count && keep; j++) {
      if (i == j || langs[j] != langs[i]) continue
      if (dirs[j] == "." && dirs[i] != ".") keep = 0
      else if (dirs[j] != "." && index(dirs[i], dirs[j] "/") == 1) keep = 0
    }
    if (keep) print dirs[i] "|" langs[i]
  }
}' | LC_ALL=C sort

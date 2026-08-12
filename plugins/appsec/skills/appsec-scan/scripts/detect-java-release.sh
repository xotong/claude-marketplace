#!/usr/bin/env sh
# =============================================================================
# Print the highest Java release a repository targets, or nothing when the
# repository is not Java or never says.
#
# Fortify's image tag carries the JDK that COMPILES the target
# (25.2.0-jdk17-review | -jdk21-review), and the component always defaults to
# jdk17-review. A Java 21 project therefore got a JDK 17 analyzer unless an admin
# hand-pinned the image. This makes that choice automatic.
#
# The MAXIMUM across all modules is the answer, not the minimum or the first
# found: a JDK compiles its own release and every earlier one, never a later one,
# so the lowest JDK that can build the whole repository is the highest release
# declared anywhere in it.
#
# Only pom.xml and build.gradle[.kts] are read — the files that declare the
# COMPILE target. .tool-versions, .sdkmanrc and .java-version are deliberately
# ignored: they pin a developer's local toolchain, which is often newer than what
# the build actually targets, and guessing high breaks builds that guessing low
# does not.
#
# Usage:  detect-java-release.sh [root_dir]
# Prints: a major release number ("8", "17", "21") on stdout, or nothing.
# Exits:  0 when a release was printed, 1 when nothing was found. Never fails the
#         caller on a malformed build file — an unreadable version is "unknown",
#         and unknown must fall back to existing behaviour, not stop a scan.
# =============================================================================
set -eu

ROOT=${1:-.}

# "1.8" -> 8, "21.0.2" -> 21, "VERSION_17" -> 17, "VERSION_1_8" -> 8.
# Anything that is not a plain number after that is rejected, which is how a
# property placeholder (${java.version}) or a file path lands as "unknown"
# instead of as a wrong guess.
normalise() {
  n=$1
  n=${n#VERSION_}
  case "$n" in *_*) n=$(printf '%s' "$n" | tr '_' '.') ;; esac
  # Drop anything from the first character that cannot be part of a version, so
  # a quoted Gradle value ("11" / '11') loses its trailing quote.
  n=${n%%[!0-9.]*}
  case "$n" in
    1.*) n=${n#1.} ;;
  esac
  n=${n%%.*}
  case "$n" in
    '' | *[!0-9]*) return 1 ;;
  esac
  # A release below 7 or above 99 is not a Java release; it is a coincidence
  # (a <source> path fragment, a plugin version). Refuse it.
  [ "$n" -ge 7 ] 2>/dev/null || return 1
  [ "$n" -le 99 ] 2>/dev/null || return 1
  printf '%s' "$n"
}

MAX=0
consider() {
  candidate=$(normalise "$1" 2>/dev/null) || return 0
  [ "$candidate" -gt "$MAX" ] 2>/dev/null && MAX=$candidate
  return 0
}

# Build directories hold generated copies of the very files we read; a stale
# target/classes pom would otherwise outvote the real one.
find_build_files() {
  find "$ROOT" \
    -type d \( -name .git -o -name node_modules -o -name target -o -name build \
      -o -name .gradle -o -name .appsec-results -o -name .venv -o -name venv \) -prune \
    -o -type f \( -name pom.xml -o -name build.gradle -o -name build.gradle.kts \) -print \
    2>/dev/null
}

for build_file in $(find_build_files); do
  case "$build_file" in
    *pom.xml)
      # <maven.compiler.release>, <java.version>, and the compiler plugin's
      # <release>/<source>/<target>. Values are read out of the tags rather than
      # matched inline so a multi-line pom is handled the same as a dense one.
      for raw in $(grep -oE '<(maven\.compiler\.(release|source|target)|java\.version|release|source|target)>[^<]*<' \
                     "$build_file" 2>/dev/null | sed -E 's/^[^>]*>//; s/<$//'); do
        consider "$raw"
      done
      ;;
    *)
      # Gradle: toolchain first (the modern, authoritative form), then the
      # source/targetCompatibility pair in all of its spellings.
      for raw in $(grep -oE '(JavaLanguageVersion\.of|jvmToolchain)\([0-9]+\)' \
                     "$build_file" 2>/dev/null | grep -oE '[0-9]+'); do
        consider "$raw"
      done
      # [^0-9A-Za-z]* absorbs whatever sits between the key and the value — "= ",
      # a bare space (old Groovy style), and the surrounding quote of '11'.
      for raw in $(grep -oE '(source|target)Compatibility[^0-9A-Za-z]*(JavaVersion\.)?[A-Za-z_]*[0-9][0-9_.]*' \
                     "$build_file" 2>/dev/null | sed -E 's/.*Compatibility[^0-9A-Za-z]*//; s/^JavaVersion\.//'); do
        consider "$raw"
      done
      ;;
  esac
done

[ "$MAX" -gt 0 ] || exit 1
printf '%s\n' "$MAX"

#!/usr/bin/env sh
# =============================================================================
# Choose the Fortify JDK variant for a detected Java release, from the variants
# the component ACTUALLY OFFERS.
#
# The offered set is read from scanners/fortify-sast.contract
# (input.variant.option=jdkNN-review), never hardcoded here. A hardcoded
# 17-or-21 branch is how the runner stayed blind to jdk21 for so long: the
# contract recorded the option, nothing consumed it. When upstream ships
# jdk25-review, check-drift already refuses to stay quiet about it, the contract
# is regenerated as part of that bump, and this script starts selecting it with
# no further code change.
#
# Rule: the SMALLEST offered JDK that can still compile the release. A JDK
# compiles its own release and earlier ones, so the smallest sufficient one is
# the closest match to what CI would build with, and picking needlessly high
# risks toolchain incompatibilities the project never asked for.
#
# When nothing offered is new enough (release 25, only 17 and 21 published), the
# HIGHEST offered variant is printed instead: it is the best available attempt,
# and the caller warns that the JDK is behind the project.
#
# Usage:  select-jdk-variant.sh <java_release> [contract_path]
# Prints: a variant name ("jdk21-review") on stdout.
# Exits:  0 when a variant was printed, 1 when the contract offers none (in which
#         case the caller must leave the image alone rather than invent a tag).
# =============================================================================
set -eu

RELEASE=${1:-}
CONTRACT=${2:-"$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)/scanners/fortify-sast.contract"}

case "$RELEASE" in
  '' | *[!0-9]*)
    echo "ERROR: select-jdk-variant.sh needs a numeric Java release" >&2
    exit 2
    ;;
esac

[ -f "$CONTRACT" ] || exit 1

best=''
best_n=''
highest=''
highest_n=0

for option in $(grep -E '^input\.variant\.option=' "$CONTRACT" 2>/dev/null |
                  sed 's/^[^=]*=//'); do
  # jdk21-review -> 21. Anything not shaped that way is not a JDK variant.
  n=$(printf '%s' "$option" | sed -n 's/^jdk\([0-9][0-9]*\).*/\1/p')
  [ -n "$n" ] || continue

  if [ "$n" -gt "$highest_n" ]; then
    highest_n=$n
    highest=$option
  fi

  if [ "$n" -ge "$RELEASE" ]; then
    if [ -z "$best_n" ] || [ "$n" -lt "$best_n" ]; then
      best_n=$n
      best=$option
    fi
  fi
done

if [ -n "$best" ]; then
  printf '%s\n' "$best"
  exit 0
fi

if [ -n "$highest" ]; then
  printf '%s\n' "$highest"
  exit 0
fi

exit 1

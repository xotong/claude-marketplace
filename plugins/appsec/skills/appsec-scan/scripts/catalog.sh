#!/usr/bin/env bash
# =============================================================================
# Catalog      : GitLab CI/CD Catalog resolver
# Target       : Catalog component releases, templates, and runner drift
# Cache        : Component template.yml, README.md, and AGENTS.md per resolved tag
# Dependencies : curl, jq, coreutils
# =============================================================================
set -euo pipefail

usage() {
  echo "ERROR: usage: catalog.sh resolve [--offline] <instance_url> <component_path> <version> <cache_dir> [token_env] [--offline]" >&2
  echo "ERROR:    or: catalog.sh check-drift <component_path> <cache_dir> <runner_script_path|none> [configured_image]" >&2
  echo "ERROR:    or: catalog.sh contract <component_path> <cache_dir>" >&2
  echo "ERROR:    or: catalog.sh template-image <component_path> <cache_dir>" >&2
  echo "ERROR:    or: catalog.sh self-test" >&2
  exit 1
}

skill_dir() {
  local script_dir
  script_dir=$(cd "$(dirname "$0")" && pwd)
  dirname "$script_dir"
}

urlencode_path() { printf '%s' "$1" | sed 's/\//%2F/g'; }

# A transient blip (cold TLS handshake, a slow first request, a 5xx) used to
# degrade a component straight to [offline-fallback] — which reads as "the token
# is wrong" when it was only a hiccup. --retry covers transient failures and
# timeouts; it deliberately does NOT retry 401/404, so a genuine auth or path
# problem still fails fast. Timeout is tunable for slow internal instances.
#
# On failure it records the status in CATALOG_LAST_HTTP so callers can tell a
# REFUSAL apart from a failure to reach the instance. Both used to end at the
# same [offline-fallback], which is right for an unreachable instance (that is
# the airgap guarantee) and wrong for a rejected token: continuing on a snapshot
# then looks like a live check that passed.
#
# `curl -sf` collapses every 4xx and 5xx into exit 22 with no way to read the
# code back, so the status comes from one extra HEAD-shaped request made ONLY
# after a failure. A healthy run issues no additional traffic at all, and the
# fetch itself keeps its exact previous behaviour.
CATALOG_LAST_HTTP=
curl_status_probe() {
  local url token_env token_value _tmpf code timeout
  url=$1
  token_env=${2:-}
  timeout=$3
  if [ -n "$token_env" ]; then
    token_value=$(printenv "$token_env" 2>/dev/null || true)
  else
    token_value=
  fi
  if [ -n "$token_value" ]; then
    _tmpf=$(mktemp) || { printf '000'; return 0; }
    printf 'header = "PRIVATE-TOKEN: %s"\n' "$token_value" >"$_tmpf" || {
      rm -f "$_tmpf"
      printf '000'
      return 0
    }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$timeout" \
      --config "$_tmpf" "$url" 2>/dev/null || printf '000')
    rm -f "$_tmpf"
  else
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$timeout" \
      "$url" 2>/dev/null || printf '000')
  fi
  printf '%s' "$code"
}

curl_get() {
  local url token_env token_value _tmpf curl_status timeout retries
  url=$1
  token_env=${2:-}
  timeout=${APPSEC_CATALOG_TIMEOUT:-15}
  case "$timeout" in ''|*[!0-9]*) timeout=15 ;; esac
  retries=${APPSEC_CATALOG_RETRIES:-2}
  case "$retries" in ''|*[!0-9]*) retries=2 ;; esac
  if [ -n "$token_env" ]; then
    token_value=$(printenv "$token_env" 2>/dev/null || true)
  else
    token_value=
  fi
  if [ -n "$token_value" ]; then
    _tmpf=$(mktemp) || return 1
    printf 'header = "PRIVATE-TOKEN: %s"\n' "$token_value" >"$_tmpf" || {
      rm -f "$_tmpf"
      return 1
    }
    if curl -sf --max-time "$timeout" --retry "$retries" --config "$_tmpf" "$url"; then
      curl_status=0
    else
      curl_status=$?
    fi
    rm -f "$_tmpf"
  else
    if curl -sf --max-time "$timeout" --retry "$retries" "$url"; then
      curl_status=0
    else
      curl_status=$?
    fi
  fi
  CATALOG_LAST_HTTP=
  if [ "$curl_status" -ne 0 ]; then
    CATALOG_LAST_HTTP=$(curl_status_probe "$url" "$token_env" "$timeout")
  fi
  return "$curl_status"
}

# Which versions exist, normalised to [{name, commit}].
#
# Read from RELEASES, not tags. `~latest` means "the latest RELEASED catalog
# version" to GitLab, and a tag with no release behind it is not one: fortify-sast
# sat at tag 25.2.0 with zero catalog versions while this resolver called it
# healthy and [online], so a pipeline using @~latest would have failed on a
# version the skill had just approved. The component READMEs tell consumers to
# use @~latest, so that is the meaning this has to match.
#
# Tags stay as a fallback rather than a hard failure: an instance whose
# components are tagged but never released still resolves, and says so. Exact
# pins are unaffected either way — a tag is a valid git ref with or without a
# release — but see the not-published warning in fetch_online.
CATALOG_VERSION_SOURCE=
versions_json() {
  local instance_url encoded_project token_env releases_url tags_url raw count
  instance_url=$1
  encoded_project=$2
  token_env=${3:-}

  releases_url="${instance_url%/}/api/v4/projects/${encoded_project}/releases?per_page=100"
  if raw=$(curl_get "$releases_url" "$token_env" 2>/dev/null); then
    count=$(printf '%s' "$raw" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)
    if [ "${count:-0}" -gt 0 ]; then
      CATALOG_VERSION_SOURCE=releases
      printf '%s' "$raw" | jq '[.[] | {name: .tag_name, commit: (.commit.id // "")}]'
      return 0
    fi
  fi

  tags_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/tags?per_page=100"
  raw=$(curl_get "$tags_url" "$token_env" 2>/dev/null) || return 1
  CATALOG_VERSION_SOURCE=tags
  printf '%s' "$raw" | jq '[.[] | {name: .name, commit: (.commit.id // "")}]'
}

# Tag policy: strip one leading "v", exclude prereleases containing "-", then
# keep dotted numeric segments and choose the highest one numerically.
stable_release_tags() {
  jq -r '.[] | (.name // "" | sub("^v"; "")) | select(contains("-") | not) | select(test("^[0-9]+(\\.[0-9]+)*$"))'
}

prerelease_tags() {
  jq -r '.[] | (.name // "" | sub("^v"; "")) | select(contains("-"))'
}

sort_tags_desc() {
  jq -Rrsc 'split("\n") | map(select(length > 0)) | sort_by(split(".") | map(tonumber)) | reverse | .[]'
}

highest_tag() {
  jq -Rrsc 'split("\n") | map(select(length > 0)) | sort_by(split(".") | map(tonumber)) | last // empty'
}

join_tags() {
  if [ -n "${1:-}" ]; then
    printf '%s\n' "$1" | paste -sd ' ' -
  fi
}

is_newer_tag() {
  local older newer highest
  older=$1
  newer=$2
  highest=$(printf '%s\n%s\n' "$older" "$newer" | highest_tag)
  [ "$older" != "$newer" ] && [ "$highest" = "$newer" ]
}

# The commit a vendored snapshot was taken from, or "" for snapshots predating
# the stamp. Empty is not an error: it only means the move check cannot run.
snapshot_commit_of() {
  local file
  file="$(skill_dir)/reference/catalog/$1/$2/.commit"
  [ -f "$file" ] || return 0
  tr -d ' \t\n' <"$file" 2>/dev/null || true
}

fallback_tag_dir() {
  local base_dir tags tag
  base_dir=$1
  [ -d "$base_dir" ] || return 1
  tags=$(find "$base_dir" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; \
    | jq -Rrsc 'split("\n") | map(select(test("^[0-9]+(\\.[0-9]+)*$"))) | sort_by(split(".") | map(tonumber)) | last // empty')
  [ -n "$tags" ] || return 1
  tag=$tags
  [ -f "$base_dir/$tag/template.yml" ] || return 1
  printf '%s\n' "$tag"
}

fetch_template() {
  local instance_url encoded_project component_name chosen_tag token_env cache_path template_path template_url
  instance_url=$1
  encoded_project=$2
  component_name=$3
  chosen_tag=$4
  token_env=${5:-}
  cache_path=$6

  template_path="templates/${component_name}.yml"
  template_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/$(urlencode_path "$template_path")/raw?ref=${chosen_tag}"
  if curl_get "$template_url" "$token_env" >"$cache_path/template.yml.tmp"; then
    return 0
  fi

  template_path="templates/${component_name}/template.yml"
  template_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/$(urlencode_path "$template_path")/raw?ref=${chosen_tag}"
  curl_get "$template_url" "$token_env" >"$cache_path/template.yml.tmp"
}

fetch_optional_agents() {
  local instance_url encoded_project chosen_tag token_env cache_path agents_url
  instance_url=$1
  encoded_project=$2
  chosen_tag=$3
  token_env=${4:-}
  cache_path=$5

  agents_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/AGENTS.md/raw?ref=${chosen_tag}"
  if curl_get "$agents_url" "$token_env" >"$cache_path/AGENTS.md.tmp"; then
    mv "$cache_path/AGENTS.md.tmp" "$cache_path/AGENTS.md"
  else
    rm -f "$cache_path/AGENTS.md.tmp"
  fi
}

fetch_online() {
  local instance_url component_path version cache_dir token_env project_path component_name encoded_project tags_url
  local tags_json stable_tags candidate_tags chosen_tag excluded_tags cache_path readme_url newest_stable
  local tags_available chosen_commit snapshot_commit

  instance_url=$1
  component_path=$2
  version=$3
  cache_dir=$4
  token_env=${5:-}

  project_path=${component_path%/*}
  component_name=${component_path##*/}
  encoded_project=$(urlencode_path "$project_path")

  tags_json=
  tags_available=false
  if tags_json=$(versions_json "$instance_url" "$encoded_project" "$token_env"); then
    tags_available=true
    stable_tags=$(printf '%s' "$tags_json" | stable_release_tags) || return 1
    candidate_tags=$(printf '%s\n' "$stable_tags" | sort_tags_desc) || return 1
    excluded_tags=$(printf '%s' "$tags_json" | prerelease_tags) || return 1
    newest_stable=$(printf '%s\n' "$stable_tags" | highest_tag) || return 1
  else
    stable_tags=
    candidate_tags=
    excluded_tags=
    newest_stable=
  fi

  if [ "$version" = "~latest" ]; then
    [ "$tags_available" = true ] || return 1
    chosen_tag=$newest_stable
    [ -n "$chosen_tag" ] || return 1
  else
    chosen_tag=$version
  fi

  cache_path="${cache_dir%/}/${component_path}/${chosen_tag}"
  mkdir -p "$cache_path"

  fetch_template "$instance_url" "$encoded_project" "$component_name" "$chosen_tag" "$token_env" "$cache_path" || return 1

  readme_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/README.md/raw?ref=${chosen_tag}"
  curl_get "$readme_url" "$token_env" >"$cache_path/README.md.tmp" || return 1
  fetch_optional_agents "$instance_url" "$encoded_project" "$chosen_tag" "$token_env" "$cache_path"

  mv "$cache_path/template.yml.tmp" "$cache_path/template.yml"
  mv "$cache_path/README.md.tmp" "$cache_path/README.md"

  if [ "$tags_available" = true ] && [ -n "$candidate_tags" ]; then
    echo "INFO: candidate tags: $(join_tags "$candidate_tags")" >&2
    if [ -n "$excluded_tags" ]; then
      echo "INFO: chose ${chosen_tag}: highest stable release (candidates: $(join_tags "$candidate_tags"); excluded prereleases: $(join_tags "$excluded_tags"))" >&2
    else
      echo "INFO: chose ${chosen_tag}: highest stable release (candidates: $(join_tags "$candidate_tags"))" >&2
    fi
  fi

  if [ "$version" != "~latest" ] && [ -n "$newest_stable" ] && is_newer_tag "$version" "$newest_stable"; then
    echo "ADVISORY: ${component_path} pinned ${version}, newer stable ${newest_stable} available" >&2
  fi

  # An instance whose components are tagged but never released still resolves —
  # falling back rather than failing — but `include: ...@~latest` in a real
  # pipeline reads the catalog, not the tag list, so say which one answered.
  if [ "$CATALOG_VERSION_SOURCE" = tags ]; then
    echo "DRIFT: ${component_path} resolved from git tags — this project publishes no releases, so it has no CI/CD Catalog versions and '@~latest' will not resolve in a pipeline. Create a release for the tag." >&2
  fi

  # The tag a snapshot was taken at can be MOVED. fortify-sast 25.2.0 was
  # re-tagged onto new content while the vendored snapshot kept the old, and
  # nothing could tell: same tag, same filenames, different component. Record the
  # commit so the comparison below is possible at all.
  chosen_commit=$(printf '%s' "$tags_json" | jq -r --arg t "$chosen_tag" \
    '.[] | select((.name // "" | sub("^v"; "")) == $t or .name == $t) | .commit' 2>/dev/null | head -n 1)
  if [ -n "${chosen_commit:-}" ] && [ "$chosen_commit" != "null" ]; then
    printf '%s\n' "$chosen_commit" >"$cache_path/.commit"
    snapshot_commit=$(snapshot_commit_of "$component_path" "$chosen_tag")
    if [ -n "$snapshot_commit" ] && [ "$snapshot_commit" != "$chosen_commit" ]; then
      echo "DRIFT: ${component_path}@${chosen_tag} moved — the vendored snapshot came from ${snapshot_commit:0:8}, the instance now serves ${chosen_commit:0:8}. Offline runs would use the OLD component under the same tag. Re-vendor: bash scripts/revendor.sh ${instance_url} [token_env]" >&2
    fi
  fi

  printf '%s@%s [online]\n' "$component_path" "$chosen_tag"
}

resolve_cmd() {
  local instance_url component_path version cache_dir token_env offline snapshot_root snapshot_tag fallback_label
  fallback_label=offline-fallback
  instance_url=$1
  component_path=$2
  version=$3
  cache_dir=$4
  token_env=${5:-}
  offline=${6:-false}

  if [ "$offline" = true ] || [ "${CATALOG_MODE:-}" = offline ]; then
    echo "INFO: catalog offline mode for ${component_path}; using vendored snapshot" >&2
  else
    if fetch_online "$instance_url" "$component_path" "$version" "$cache_dir" "$token_env"; then
      return 0
    fi
    # A refusal is not an outage. The snapshot still gets used below — it is all
    # there is — but it must never be reported as a live check that passed, so
    # say which of the two happened.
    case "${CATALOG_LAST_HTTP:-}" in
      401|403)
        echo "CONFIG-ERROR: ${instance_url} refused our catalogue credentials (HTTP ${CATALOG_LAST_HTTP}) for ${component_path} — the token named by settings.catalog.auth_token_env${token_env:+ (\$$token_env)} is missing, expired, or lacks read_api. The vendored snapshot below is NOT a substitute: it cannot tell you the component has changed." >&2
        # Carried into the resolution table Step 2.5 shows the user verbatim, so
        # the distinction survives past this one stderr line.
        fallback_label="offline-fallback: unauthorized"
        ;;
      *)
        echo "WARN: catalog resolve failed online for ${component_path}; trying vendored snapshot" >&2
        ;;
    esac
  fi

  snapshot_root="$(skill_dir)/reference/catalog/${component_path}"

  if [ "$version" != "~latest" ] && [ -f "$snapshot_root/$version/template.yml" ]; then
    snapshot_tag=$version
  else
    snapshot_tag=$(fallback_tag_dir "$snapshot_root" || true)
    if [ "$version" != "~latest" ] && [ -n "$snapshot_tag" ]; then
      echo "WARN: vendored snapshot for pinned ${component_path}@${version} not found; using ${snapshot_tag}" >&2
    fi
  fi

  if [ -n "${snapshot_tag:-}" ]; then
    echo "INFO: using snapshot ${component_path}@${snapshot_tag}" >&2
    printf '%s@%s [%s]\n' "$component_path" "$snapshot_tag" "$fallback_label"
    return 0
  fi

  echo "ERROR: no vendored catalog snapshot found for ${component_path}" >&2
  return 1
}

# Effective image ref of the component's first job. Handles a literal
# "registry/name:tag" and $[[ inputs.X ]] interpolation, substituting each
# input's declared default. Prints nothing when the ref resolves to a shell
# variable the template does not declare (e.g. "$DS_ANALYZER_IMAGE") — that is
# genuinely underivable, and reporting it as "no drift" would be a lie.
template_image_ref() {
  awk '
    function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
    function unquote(s) {
      if (s ~ /^".*"$/ || s ~ /^\047.*\047$/) return substr(s, 2, length(s) - 2)
      return s
    }
    /^spec:[ \t]*$/ { in_spec = 1; next }
    in_spec && /^[^ \t]/ { in_spec = 0 }
    in_spec {
      if ($0 ~ /^    [A-Za-z0-9_.-]+:[ \t]*$/) { name = trim($0); sub(/:$/, "", name); next }
      if (name != "" && $0 ~ /^      default:/) {
        v = $0; sub(/^      default:[ \t]*/, "", v)
        def[name] = unquote(trim(v)); name = ""
      }
      next
    }
    # variables: blocks, at document level (keys indented 2) and inside a job
    # (keys indented 4). dependency-scanning builds its image through these
    # rather than through spec.inputs:
    #   variables: {ANALYZER_IMAGE_PREFIX, ANALYZER_IMAGE_NAME, ANALYZER_IMAGE_VERSION}
    #   job.variables.DS_ANALYZER_IMAGE: $PREFIX/$NAME:$VERSION
    #   job.image: "$DS_ANALYZER_IMAGE"
    # Without resolving them the ref is underivable and the category needs an
    # explicit image: in config.
    /^variables:[ \t]*$/  { in_vars = 1; vars_indent = 2; next }
    /^  variables:[ \t]*$/ { in_vars = 1; vars_indent = 4; next }
    in_vars {
      if ($0 ~ /^[ \t]*$/) next
      if ($0 ~ /^[ \t]*#/) next
      indent = match($0, /[^ ]/) - 1
      if (indent >= vars_indent) {
        line = trim($0); idx = index(line, ":")
        if (idx > 1) {
          vk = substr(line, 1, idx - 1)
          vv = unquote(trim(substr(line, idx + 1)))
          if (!(vk in varmap)) varmap[vk] = vv
        }
        next
      }
      in_vars = 0
    }
    image == "" && $0 ~ /^  image:[ \t]/ {
      v = $0; sub(/^  image:[ \t]*/, "", v); image = unquote(trim(v))
    }
    END {
      if (image == "") exit 0
      # Alternate between input and variable expansion: a variable value may
      # itself contain $[[ inputs.x ]], and vice versa. Bounded so a self
      # referential definition cannot spin.
      for (pass = 0; pass < 20; pass++) {
        if (match(image, /\$\[\[[ \t]*inputs\.[A-Za-z0-9_.-]+[ \t]*\]\]/)) {
          k = substr(image, RSTART, RLENGTH)
          sub(/^\$\[\[[ \t]*inputs\./, "", k); sub(/[ \t]*\]\]$/, "", k)
          if (!(k in def)) exit 0
          image = substr(image, 1, RSTART - 1) def[k] substr(image, RSTART + RLENGTH)
          continue
        }
        if (match(image, /\$\{[A-Za-z_][A-Za-z0-9_]*\}/)) {
          k = substr(image, RSTART + 2, RLENGTH - 3)
          if (!(k in varmap)) exit 0
          image = substr(image, 1, RSTART - 1) varmap[k] substr(image, RSTART + RLENGTH)
          continue
        }
        if (match(image, /\$[A-Za-z_][A-Za-z0-9_]*/)) {
          k = substr(image, RSTART + 1, RLENGTH - 1)
          if (!(k in varmap)) exit 0
          image = substr(image, 1, RSTART - 1) varmap[k] substr(image, RSTART + RLENGTH)
          continue
        }
        break
      }
      if (image ~ /\$/) exit 0
      print image
    }
  ' "$1"
}

# Machine-readable contract of a component template: the inputs it declares
# (defaults and permitted options) and the report artifacts it produces.
# Sorted flat text on purpose — no jq/python dependency, and it diffs cleanly in
# review. The image ref is deliberately NOT included: check-drift compares that
# separately, and folding it in here would churn the checked-in contract on
# every image bump.
#
# template.yml is the only source of truth. AGENTS.md is narrative and is known
# to lag it (as of 25.2.0 it still omits the `go` language and names the
# pre-move registry), so it must never drive behaviour.
template_contract() {
  awk '
    function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
    function unquote(s) {
      if (s ~ /^".*"$/ || s ~ /^\047.*\047$/) return substr(s, 2, length(s) - 2)
      return s
    }
    /^spec:[ \t]*$/ { in_spec = 1; next }
    in_spec && /^[^ \t]/ { in_spec = 0 }
    in_spec {
      if ($0 ~ /^    [A-Za-z0-9_.-]+:[ \t]*$/) {
        name = trim($0); sub(/:$/, "", name); in_opts = 0; next
      }
      if (name == "") next
      if ($0 ~ /^      default:/) {
        v = $0; sub(/^      default:[ \t]*/, "", v)
        print "input." name ".default=" unquote(trim(v)); in_opts = 0; next
      }
      if ($0 ~ /^      options:[ \t]*$/) { in_opts = 1; next }
      if (in_opts && $0 ~ /^        -[ \t]*/) {
        v = $0; sub(/^        -[ \t]*/, "", v)
        print "input." name ".option=" unquote(trim(v)); next
      }
      if ($0 ~ /^      [A-Za-z0-9_.-]+:/) { in_opts = 0 }
      next
    }
    /^    reports:[ \t]*$/ { in_reports = 1; next }
    in_reports {
      if ($0 ~ /^      [A-Za-z0-9_]+:[ \t]*[^ \t]/) {
        line = trim($0); idx = index(line, ":")
        print "report." substr(line, 1, idx - 1) "=" unquote(trim(substr(line, idx + 1)))
        next
      }
      in_reports = 0
    }
  ' "$1" | LC_ALL=C sort -u
}

# Compare a component's derived contract against the runner's checked-in
# expectation (scanners/<runner>.contract). Emits one CONTRACT-DRIFT line per
# differing key. This is the check that would have caught the `go` language
# option being added to fortify-sast without any runner support.
contract_drift() {
  local template_path expected_path label actual_file expected_file only_upstream only_local
  template_path=$1
  expected_path=$2
  label=$3

  actual_file=$(mktemp) || return 0
  expected_file=$(mktemp) || { rm -f "$actual_file"; return 0; }
  template_contract "$template_path" >"$actual_file"
  # Contract files carry a #-comment header explaining what they are; strip it
  # so the header never registers as drift.
  grep -v '^#' "$expected_path" | grep -v '^[[:space:]]*$' | LC_ALL=C sort -u >"$expected_file"

  only_upstream=$(LC_ALL=C comm -23 "$actual_file" "$expected_file")
  only_local=$(LC_ALL=C comm -13 "$actual_file" "$expected_file")
  rm -f "$actual_file" "$expected_file"

  if [ -n "$only_upstream" ]; then
    printf '%s\n' "$only_upstream" | while IFS= read -r line; do
      [ -n "$line" ] && printf 'CONTRACT-DRIFT: %s: component now declares %s\n' "$label" "$line"
    done
  fi
  if [ -n "$only_local" ]; then
    printf '%s\n' "$only_local" | while IFS= read -r line; do
      [ -n "$line" ] && printf 'CONTRACT-DRIFT: %s: contract expects %s but the component no longer declares it\n' "$label" "$line"
    done
  fi
}

date_to_epoch() {
  local epoch
  # ponytail: probes by success not uname; add awk fallback if date portability widens.
  if epoch=$(date -d "$1 00:00:00" +%s 2>/dev/null); then
    printf '%s\n' "$epoch"
  elif epoch=$(gdate -d "$1" +%s 2>/dev/null); then
    printf '%s\n' "$epoch"
  elif epoch=$(date -j -f '%Y-%m-%d' "$1" +%s 2>/dev/null); then
    printf '%s\n' "$epoch"
  else
    printf '0\n'
  fi
}

# Print the component template's effective job image at the resolved tag, or
# nothing when the template builds it from a shell variable the template does not
# declare (e.g. dependency-scanning's $DS_ANALYZER_IMAGE). Prints nothing rather
# than guessing — callers treat empty as "keep what the admin configured".
template_image_cmd() {
  local component_path cache_dir base_dir tag
  component_path=$1
  cache_dir=$2
  base_dir="${cache_dir%/}/${component_path}"
  [ -d "$base_dir" ] || base_dir="$(skill_dir)/reference/catalog/${component_path}"
  tag=$(fallback_tag_dir "$base_dir" || true)
  [ -n "$tag" ] || return 0
  template_image_ref "$base_dir/$tag/template.yml"
}

check_drift_cmd() {
  local component_path cache_dir runner_path configured_image base_dir tag template_path runner_name
  local synced_line synced_date now_epoch synced_epoch ninety_days template_image contract_expected

  component_path=$1
  cache_dir=$2
  runner_path=$3
  configured_image=${4:-}
  base_dir="${cache_dir%/}/${component_path}"

  if [ ! -d "$base_dir" ]; then
    base_dir="$(skill_dir)/reference/catalog/${component_path}"
  fi

  tag=$(fallback_tag_dir "$base_dir" || true)
  [ -n "$tag" ] || {
    echo "INFO: no cached or vendored catalog snapshot found for ${component_path}" >&2
    return 0
  }

  template_path="$base_dir/$tag/template.yml"
  template_image=$(template_image_ref "$template_path")

  echo "INFO: checking runner drift against ${component_path}@${tag}" >&2

  if [ -z "$template_image" ]; then
    echo "INFO: component template declares no resolvable image - skipping image drift check" >&2
  elif [ -z "$configured_image" ]; then
    echo "INFO: no configured image passed - skipping image drift check" >&2
  elif [ "$template_image" != "$configured_image" ]; then
    printf 'DRIFT: image drift: configured %s vs component template %s\n' "$configured_image" "$template_image"
  fi

  if [ "$runner_path" != "none" ] && [ -f "$runner_path" ]; then
    runner_name=$(basename "$runner_path")

    contract_expected="${runner_path%.sh}.contract"
    if [ -f "$contract_expected" ]; then
      contract_drift "$template_path" "$contract_expected" "$runner_name"
    else
      echo "INFO: no checked-in contract at $(basename "$contract_expected") - skipping contract drift check" >&2
    fi

    synced_line=$(grep -E '^# Last synced[[:space:]]*:' "$runner_path" | head -n 1 || true)
    synced_date=$(printf '%s' "$synced_line" | sed -E 's/^# Last synced[[:space:]]*:[[:space:]]*//')
    if printf '%s' "$synced_date" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
      now_epoch=$(date_to_epoch "$(date +%F)")
      synced_epoch=$(date_to_epoch "$synced_date")
      ninety_days=$((90 * 24 * 60 * 60))
      if [ $((now_epoch - synced_epoch)) -gt "$ninety_days" ]; then
        printf 'DRIFT: runner %s last synced %s - review against %s@%s\n' "$runner_name" "$synced_date" "$component_path" "$tag"
      fi
    fi
  fi
}

# Print the derived contract for a component, for regenerating the checked-in
# scanners/<runner>.contract files. See UPDATE-GUIDE.md Scenario 6.
contract_cmd() {
  local component_path cache_dir base_dir tag
  component_path=$1
  cache_dir=$2
  base_dir="${cache_dir%/}/${component_path}"
  [ -d "$base_dir" ] || base_dir="$(skill_dir)/reference/catalog/${component_path}"

  tag=$(fallback_tag_dir "$base_dir" || true)
  if [ -z "$tag" ]; then
    echo "ERROR: no cached or vendored catalog snapshot found for ${component_path}" >&2
    return 1
  fi
  echo "INFO: contract derived from ${component_path}@${tag}" >&2
  template_contract "$base_dir/$tag/template.yml"
}

self_test_cmd() {
  local tmp root script cache component out drift advisory
  tmp=$(mktemp -d)
  CATALOG_SELFTEST_TMP=$tmp
  trap 'rm -rf "${CATALOG_SELFTEST_TMP-}"; unset CATALOG_SELFTEST_TMP; trap - RETURN' RETURN

  root="$tmp/appsec-scan"
  script="$root/scripts/catalog.sh"
  cache="$tmp/cache"
  # Neutral fixture path: the self-test must not imply a real catalogue layout.
  component="example-group/devops/catalogue/secret-detection/secret-detection"

  mkdir -p "$root/scripts" "$root/reference/catalog/$component/1.0.0" "$tmp/bin" "$cache"
  cp "$0" "$script"
  # Fixture shape mirrors the real secret-detection template: a literal job
  # image, NOT a synthetic image_tag input. A fixture that does not look like
  # the catalogue is how drift detection stayed green while doing nothing.
  printf '%s\n' 'spec:' '  inputs:' '    stage:' '      default: test' '---' \
    'scan:' '  image: "registry.example/secrets:7"' \
    >"$root/reference/catalog/$component/1.0.0/template.yml"
  printf '# README\n' >"$root/reference/catalog/$component/1.0.0/README.md"
  printf '# AGENTS\n' >"$root/reference/catalog/$component/1.0.0/AGENTS.md"

  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'url=${!#}' \
    'case "$url" in' \
    '  */repository/tags?per_page=100) printf "%s\n" "[{\"name\":\"1.1.0\"},{\"name\":\"1.0.0\"},{\"name\":\"0.9.0\"},{\"name\":\"1.2.0-rc1\"}]" ;;' \
    '  */repository/files/templates%2Fsecret-detection.yml/raw?ref=1.1.0) printf "%s\n" "spec:" "---" "scan:" "  image: \"registry.example/secrets:7.1\"" ;;' \
    '  */repository/files/templates%2Fsecret-detection.yml/raw?ref=1.0.0) printf "%s\n" "spec:" "---" "scan:" "  image: \"registry.example/secrets:7\"" ;;' \
    '  */repository/files/templates%2Fsecret-detection%2Ftemplate.yml/raw?ref=1.1.0) printf "%s\n" "spec:" "---" "scan:" "  image: \"registry.example/secrets:7.1\"" ;;' \
    '  */repository/files/templates%2Fsecret-detection%2Ftemplate.yml/raw?ref=1.0.0) printf "%s\n" "spec:" "---" "scan:" "  image: \"registry.example/secrets:7\"" ;;' \
    '  */repository/files/README.md/raw?ref=1.1.0) printf "%s\n" "# README" ;;' \
    '  */repository/files/README.md/raw?ref=1.0.0) printf "%s\n" "# README" ;;' \
    '  */repository/files/AGENTS.md/raw?ref=1.1.0) printf "%s\n" "# AGENTS" ;;' \
    '  */repository/files/AGENTS.md/raw?ref=1.0.0) printf "%s\n" "# AGENTS" ;;' \
    '  *) exit 22 ;;' \
    'esac' >"$tmp/bin/curl"
  chmod +x "$tmp/bin/curl"

  out=$(PATH="$tmp/bin:$PATH" bash "$script" resolve https://gitlab.example.com "$component" ~latest "$cache")
  [ "$out" = "$component@1.1.0 [online]" ] || return 1

  advisory=$(PATH="$tmp/bin:$PATH" bash "$script" resolve https://gitlab.example.com "$component" 1.0.0 "$cache" 2>&1)
  printf '%s\n' "$advisory" | grep -q "$component@1.0.0 \[online\]" || return 1
  printf '%s\n' "$advisory" | grep -q "ADVISORY: ${component} pinned 1.0.0, newer stable 1.1.0 available" || return 1

  printf '%s\n' '#!/usr/bin/env bash' 'exit 22' >"$tmp/bin/curl"
  chmod +x "$tmp/bin/curl"

  out=$(PATH="$tmp/bin:$PATH" bash "$script" resolve https://gitlab.example.com "$component" ~latest "$cache")
  [ "$out" = "$component@1.0.0 [offline-fallback]" ] || return 1

  printf '%s\n' '# Last synced: 2024-01-01' >"$tmp/runner.sh"
  drift=$(bash "$script" check-drift "$component" "$cache" "$tmp/runner.sh")
  printf '%s\n' "$drift" | grep -q '^DRIFT: runner ' || return 1

  # Image drift, the three shapes the real catalogue actually uses.
  # $cache resolves to tag 1.1.0, whose template declares secrets:7.1.
  # 1. literal ref, configured tag behind the template's
  drift=$(bash "$script" check-drift "$component" "$cache" none "registry.example/secrets:6")
  printf '%s\n' "$drift" | grep -q '^DRIFT: image drift: .*secrets:6 .*secrets:7\.1' || return 1

  # 2. literal ref, configured image matches - must stay silent
  drift=$(bash "$script" check-drift "$component" "$cache" none "registry.example/secrets:7.1")
  if printf '%s\n' "$drift" | grep -q '^DRIFT: image'; then return 1; fi

  # 3. $[[ inputs.X ]] interpolation resolved from declared defaults
  mkdir -p "$tmp/interp/$component/9.9.9"
  printf '%s\n' 'spec:' '  inputs:' '    registry:' '      default: reg.example/' \
    '    image:' '      default: sca' '    image-tag:' '      default: "25.2.0"' \
    '    variant:' '      default: jdk17' '---' \
    'scan:' '  image: $[[ inputs.registry ]]$[[ inputs.image ]]:$[[ inputs.image-tag ]]-$[[ inputs.variant ]]' \
    >"$tmp/interp/$component/9.9.9/template.yml"
  drift=$(bash "$script" check-drift "$component" "$tmp/interp" none "reg.example/sca:24.1.0-jdk17")
  printf '%s\n' "$drift" | grep -q '^DRIFT: image drift: .*sca:24.1.0-jdk17 .*sca:25.2.0-jdk17' || return 1

  # 4. image from an undeclared shell variable - underivable, must say so
  #    rather than silently reporting no drift
  mkdir -p "$tmp/shellvar/$component/9.9.9"
  printf '%s\n' 'spec:' '---' 'scan:' '  image: "$DS_ANALYZER_IMAGE"' \
    >"$tmp/shellvar/$component/9.9.9/template.yml"
  drift=$(bash "$script" check-drift "$component" "$tmp/shellvar" none "anything:1" 2>&1)
  printf '%s\n' "$drift" | grep -q 'declares no resolvable image' || return 1
  if printf '%s\n' "$drift" | grep -q '^DRIFT: image'; then return 1; fi

  # Contract extraction + drift, the check that catches a new input or option.
  mkdir -p "$tmp/contract/$component/9.9.9"
  printf '%s\n' 'spec:' '  inputs:' '    language:' '      default: "javascript"' \
    '      options:' '        - javascript' '        - go' '    stage:' '      default: test' '---' \
    'scan:' '  image: "registry.example/secrets:7"' '  artifacts:' '    reports:' \
    '      sast: gl-sast-report.json' \
    >"$tmp/contract/$component/9.9.9/template.yml"

  out=$(bash "$script" contract "$component" "$tmp/contract" 2>/dev/null)
  printf '%s\n' "$out" | grep -qx 'input.language.option=go' || return 1
  printf '%s\n' "$out" | grep -qx 'input.language.default=javascript' || return 1
  printf '%s\n' "$out" | grep -qx 'report.sast=gl-sast-report.json' || return 1

  # A contract missing the new option must drift; a matching one must not.
  printf '%s\n' '# header comment must not register as drift' \
    'input.language.default=javascript' 'input.language.option=javascript' \
    'input.stage.default=test' 'report.sast=gl-sast-report.json' >"$tmp/stale.contract"
  cp "$tmp/runner.sh" "$tmp/c-runner.sh"
  cp "$tmp/stale.contract" "$tmp/c-runner.contract"
  drift=$(bash "$script" check-drift "$component" "$tmp/contract" "$tmp/c-runner.sh" 2>/dev/null)
  printf '%s\n' "$drift" | grep -q 'CONTRACT-DRIFT: .*component now declares input.language.option=go' || return 1

  bash "$script" contract "$component" "$tmp/contract" 2>/dev/null >"$tmp/c-runner.contract"
  drift=$(bash "$script" check-drift "$component" "$tmp/contract" "$tmp/c-runner.sh" 2>/dev/null)
  if printf '%s\n' "$drift" | grep -q 'CONTRACT-DRIFT'; then return 1; fi

  printf '%s\n' \
    'self-test: online path ok' \
    'self-test: pinned path advisory ok' \
    'self-test: offline-fallback path ok' \
    'self-test: check-drift runner-staleness DRIFT ok' \
    'self-test: image drift literal mismatch ok' \
    'self-test: image drift literal match silent ok' \
    'self-test: image drift inputs-interpolation ok' \
    'self-test: image drift underivable reported ok' \
    'self-test: contract extraction ok' \
    'self-test: contract drift on new option ok' \
    'self-test: contract match silent ok'
}

main() {
  local offline
  [ $# -ge 1 ] || usage
  case "$1" in
    resolve)
      offline=false
      if [ "${2:-}" = --offline ]; then
        offline=true
        shift
      fi
      [ $# -ge 5 ] && [ $# -le 7 ] || usage
      if [ "${7:-}" = --offline ]; then
        offline=true
      elif [ $# -eq 7 ]; then
        usage
      fi
      if [ "${6:-}" = --offline ]; then
        offline=true
        resolve_cmd "$2" "$3" "$4" "$5" "" "$offline"
      else
        resolve_cmd "$2" "$3" "$4" "$5" "${6:-}" "$offline"
      fi
      ;;
    check-drift)
      [ $# -eq 4 ] || [ $# -eq 5 ] || usage
      check_drift_cmd "$2" "$3" "$4" "${5:-}"
      ;;
    template-image)
      [ $# -eq 3 ] || usage
      template_image_cmd "$2" "$3"
      ;;
    contract)
      [ $# -eq 3 ] || usage
      contract_cmd "$2" "$3"
      ;;
    self-test)
      [ $# -eq 1 ] || usage
      self_test_cmd
      ;;
    *)
      usage
      ;;
  esac
}

main "$@"

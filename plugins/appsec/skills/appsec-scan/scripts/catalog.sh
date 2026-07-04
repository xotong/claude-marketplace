#!/usr/bin/env bash
# =============================================================================
# Catalog      : GitLab CI/CD Catalog resolver
# Target       : Catalog component releases, templates, and runner drift
# Cache        : Component template.yml and README.md per resolved tag
# Dependencies : curl, jq, coreutils
# =============================================================================
set -euo pipefail
usage() {
  echo "ERROR: usage: catalog.sh resolve <instance_url> <component_path> <cache_dir> [token_env]" >&2
  echo "ERROR:    or: catalog.sh check-drift <component_path> <cache_dir> <runner_script_path|none>" >&2
  exit 1
}
skill_dir() {
  local script_path script_dir
  script_path=$(realpath "$0"); script_dir=$(dirname "$script_path")
  dirname "$script_dir"
}
urlencode_path() { printf '%s' "$1" | sed 's/\//%2F/g'; }
curl_get() {
  local url token_env token_value
  url=$1
  token_env=${2:-}
  if [ -n "$token_env" ]; then
    token_value=$(printenv "$token_env" 2>/dev/null || true)
  else
    token_value=
  fi
  if [ -n "$token_value" ]; then
    curl -sf --max-time 10 -H "PRIVATE-TOKEN: $token_value" "$url"
  else
    curl -sf --max-time 10 "$url"
  fi
}
# Tag policy: strip one leading "v", exclude prereleases containing "-", then
# keep dotted numeric segments and choose the highest one numerically.
stable_release_tags() {
  jq -r '.[] | (.name // "" | sub("^v"; "")) | select(contains("-") | not) | select(test("^[0-9]+(\\.[0-9]+)*$"))'
}
prerelease_tags() {
  jq -r '.[] | (.name // "" | sub("^v"; "")) | select(contains("-"))'
}
sort_tags_desc() { jq -Rrsc 'split("\n") | map(select(length > 0)) | sort_by(split(".") | map(tonumber)) | reverse | .[]'; }
highest_tag() { jq -Rrsc 'split("\n") | map(select(length > 0)) | sort_by(split(".") | map(tonumber)) | last // empty'; }
join_tags() { if [ -n "${1:-}" ]; then printf '%s\n' "$1" | paste -sd ' ' -; fi; }
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
fetch_online() {
  local instance_url component_path cache_dir token_env project_path component_name encoded_project tags_url tags_json
  local stable_tags candidate_tags chosen_tag excluded_tags cache_path readme_url template_path template_url
  instance_url=$1
  component_path=$2
  cache_dir=$3
  token_env=${4:-}
  project_path=${component_path%/*}
  component_name=${component_path##*/}
  encoded_project=$(urlencode_path "$project_path")
  tags_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/tags?per_page=100"
  tags_json=$(curl_get "$tags_url" "$token_env") || return 1
  stable_tags=$(printf '%s' "$tags_json" | stable_release_tags) || return 1
  chosen_tag=$(printf '%s\n' "$stable_tags" | highest_tag) || return 1
  [ -n "$chosen_tag" ] || return 1
  candidate_tags=$(printf '%s\n' "$stable_tags" | sort_tags_desc) || return 1
  excluded_tags=$(printf '%s' "$tags_json" | prerelease_tags) || return 1
  cache_path="${cache_dir%/}/${component_path}/${chosen_tag}"
  mkdir -p "$cache_path"
  readme_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/README.md/raw?ref=${chosen_tag}"
  template_path="templates/${component_name}.yml"
  template_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/$(urlencode_path "$template_path")/raw?ref=${chosen_tag}"
  if ! curl_get "$template_url" "$token_env" >"$cache_path/template.yml.tmp"; then
    template_path="templates/${component_name}/template.yml"
    template_url="${instance_url%/}/api/v4/projects/${encoded_project}/repository/files/$(urlencode_path "$template_path")/raw?ref=${chosen_tag}"
    curl_get "$template_url" "$token_env" >"$cache_path/template.yml.tmp" || return 1
  fi
  curl_get "$readme_url" "$token_env" >"$cache_path/README.md.tmp" || return 1
  mv "$cache_path/template.yml.tmp" "$cache_path/template.yml"
  mv "$cache_path/README.md.tmp" "$cache_path/README.md"

  echo "INFO: candidate tags: $(join_tags "$candidate_tags")" >&2
  if [ -n "$excluded_tags" ]; then
    echo "INFO: chose ${chosen_tag}: highest stable release (candidates: $(join_tags "$candidate_tags"); excluded prereleases: $(join_tags "$excluded_tags"))" >&2
  else
    echo "INFO: chose ${chosen_tag}: highest stable release (candidates: $(join_tags "$candidate_tags"))" >&2
  fi
  printf '%s@%s [online]\n' "$component_path" "$chosen_tag"
}
resolve_cmd() {
  local instance_url component_path cache_dir token_env snapshot_root snapshot_tag
  instance_url=$1
  component_path=$2
  cache_dir=$3
  token_env=${4:-}
  if fetch_online "$instance_url" "$component_path" "$cache_dir" "$token_env"; then
    return 0
  fi
  echo "WARN: catalog resolve failed online for ${component_path}; trying vendored snapshot" >&2
  snapshot_root="$(skill_dir)/reference/catalog/${component_path}"
  snapshot_tag=$(fallback_tag_dir "$snapshot_root" || true)
  if [ -n "$snapshot_tag" ]; then
    echo "INFO: using snapshot ${component_path}@${snapshot_tag}" >&2
    printf '%s@%s [offline-fallback]\n' "$component_path" "$snapshot_tag"
    return 0
  fi

  echo "ERROR: no vendored catalog snapshot found for ${component_path}" >&2
  return 1
}
extract_image_tag_default() {
  awk '
    /^[[:space:]]*spec:[[:space:]]*$/ { in_spec=1; next }
    in_spec && /^[[:space:]]*inputs:[[:space:]]*$/ { in_inputs=1; next }
    in_inputs && /^[[:space:]]*image_tag:[[:space:]]*$/ { in_tag=1; next }
    in_tag && /^[[:space:]]*default:[[:space:]]*/ {
      value=$0
      sub(/^[[:space:]]*default:[[:space:]]*/, "", value)
      gsub(/^["'\''"]|["'\''"]$/, "", value)
      print value
      exit
    }
  ' "$1"
}
date_to_epoch() {
  if command -v gdate >/dev/null 2>&1; then
    gdate -d "$1" +%s
  else
    date -j -f "%Y-%m-%d" "$1" +%s
  fi
}
runner_image_tag_default() {
  grep -Eo '[A-Z0-9_]+TAG:-[^}[:space:]"]+' "$1" | head -n 1 | sed 's/.*TAG:-//'
}
check_drift_cmd() {
  local component_path cache_dir runner_path base_dir tag template_path template_tag runner_name
  local synced_line synced_date now_epoch synced_epoch ninety_days runner_tag
  component_path=$1
  cache_dir=$2
  runner_path=$3
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
  template_tag=$(extract_image_tag_default "$template_path")
  if [ -z "$template_tag" ]; then
    echo "INFO: no image_tag input - skipping image drift check" >&2
    return 0
  fi
  echo "INFO: checking runner drift against ${component_path}@${tag}" >&2
  if [ "$runner_path" != "none" ] && [ -f "$runner_path" ]; then
    runner_name=$(basename "$runner_path")
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

    runner_tag=$(runner_image_tag_default "$runner_path" || true)
    if [ -n "$runner_tag" ] && [ "$runner_tag" != "$template_tag" ]; then
      printf 'DRIFT: image tag drift: runner default %s vs component default %s\n' "$runner_tag" "$template_tag"
    fi
  fi
}
self_test_cmd() {
  local tmp root script cache component out drift
  tmp=$(mktemp -d); CATALOG_SELFTEST_TMP=$tmp
  trap 'rm -rf "${CATALOG_SELFTEST_TMP-}"; unset CATALOG_SELFTEST_TMP; trap - RETURN' RETURN
  root="$tmp/appsec-scan"; script="$root/scripts/catalog.sh"; cache="$tmp/cache"; component="components/secret-detection/secret-detection"
  mkdir -p "$root/scripts" "$root/reference/catalog/$component/2.3.0" "$tmp/bin" "$cache"
  cp "$0" "$script"
  printf '%s\n' 'spec:' '  inputs:' '    image_tag:' '      default: "2.3.0"' >"$root/reference/catalog/$component/2.3.0/template.yml"
  printf '# README\n' >"$root/reference/catalog/$component/2.3.0/README.md"
  printf '%s\n' '#!/usr/bin/env bash' 'url=${!#}' 'case "$url" in' \
    '  */repository/tags?per_page=100) printf "%s\n" "[{\"name\":\"2.3.0\"},{\"name\":\"2.2.9\"},{\"name\":\"1.0.0\"},{\"name\":\"v0.9.0\"},{\"name\":\"2.4.0-rc1\"}]" ;;' \
    '  */repository/files/templates%2Fsecret-detection.yml/raw?ref=2.3.0) exit 22 ;;' \
    '  */repository/files/templates%2Fsecret-detection%2Ftemplate.yml/raw?ref=2.3.0) printf "%s\n" "spec:" "  inputs:" "    image_tag:" "      default: \"2.3.0\"" ;;' \
    '  */repository/files/README.md/raw?ref=2.3.0) printf "%s\n" "# README" ;;' \
    '  *) exit 22 ;;' 'esac' >"$tmp/bin/curl"
  chmod +x "$tmp/bin/curl"
  out=$(PATH="$tmp/bin:$PATH" bash "$script" resolve https://gitlab.example.com "$component" "$cache"); [ "$out" = "$component@2.3.0 [online]" ] || return 1
  printf '%s\n' '#!/usr/bin/env bash' 'exit 22' >"$tmp/bin/curl"
  chmod +x "$tmp/bin/curl"
  out=$(PATH="$tmp/bin:$PATH" bash "$script" resolve https://gitlab.example.com "$component" "$cache"); [ "$out" = "$component@2.3.0 [offline-fallback]" ] || return 1
  printf '%s\n' '# Last synced: 2024-01-01' 'image=${SECDET_TAG:-9.9.9}' >"$tmp/runner.sh"
  drift=$(bash "$script" check-drift "$component" "$cache" "$tmp/runner.sh"); printf '%s\n' "$drift" | grep -q '^DRIFT:' || return 1
  printf '%s\n' 'self-test: online path ok' 'self-test: offline-fallback path ok' 'self-test: check-drift DRIFT line ok'
}
main() {
  [ $# -ge 1 ] || usage
  case "$1" in
    resolve) [ $# -ge 4 ] && [ $# -le 5 ] || usage; resolve_cmd "$2" "$3" "$4" "${5:-}" ;;
    check-drift) [ $# -eq 4 ] || usage; check_drift_cmd "$2" "$3" "$4" ;;
    self-test) [ $# -eq 1 ] || usage; self_test_cmd ;;
    *)
      usage
      ;;
  esac
}
main "$@"

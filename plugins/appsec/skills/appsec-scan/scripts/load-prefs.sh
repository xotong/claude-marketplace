#!/usr/bin/env bash
#
# load-prefs.sh emits bash-sourceable assignments for the shipped
# scanner-preferences.yaml shape. It is intentionally NOT a general YAML parser.
# Supported subset only:
#   - 2-space indentation
#   - key: value scalars (bare or quoted)
#   - blank lines and #-comment lines
#   - settings.airgap
#   - settings.container_runtime
#   - settings.jq.install_url
#   - settings.python.install_url
#   - settings.catalog.mode
#   - settings.catalog.auth_token_env
#   - settings.container_registry.user_env
#   - settings.container_registry.password_env
#   - settings.ci_gate.fail_on
#   - default_profile
#   - profiles.<name>.gitlab_instance
#   - profiles.<name>.categories.<category>.{component,version,image,runner,enabled}
#
# Runner -> RUN_* mapping. Keep this table aligned with the case statement below;
# it is the single source of truth referenced from SKILL.md.
#   fortify-sast.sh              -> RUN_FORTIFY_SAST
#   gitlab-dependency-scanning.sh -> RUN_GITLAB_DS
#   secret-detection.sh          -> RUN_SECRET_DETECTION
#   gitlab-container-scanning.sh -> RUN_GITLAB_CS
#   none                         -> no flag

set -u

emit() {
  printf 'export %s=%q\n' "$1" "$2"
}

warn() {
  printf '%s\n' "$*" >&2
}

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
  warn "Usage: load-prefs.sh <path-to-scanner-preferences.yaml>"
  exit 1
fi

config_path=$1
if [ ! -r "$config_path" ]; then
  warn "ERROR: config file is missing or unreadable: $config_path"
  exit 1
fi

requested_profile=
if [ -n "${APPSEC_PROFILE:-}" ]; then
  requested_profile=$APPSEC_PROFILE
fi

tmp_output=$(mktemp "${TMPDIR:-/tmp}/load-prefs.XXXXXX") || exit 1
cleanup() {
  rm -f "$tmp_output"
}
trap cleanup EXIT INT TERM HUP

if ! awk -v requested_profile="$requested_profile" '
function trim(s) {
  sub(/^[ \t]+/, "", s)
  sub(/[ \t]+$/, "", s)
  return s
}

function strip_comment(s,    out, i, c, prev, in_quote) {
  out = ""
  in_quote = 0
  prev = ""
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c == "\"" && prev != "\\") {
      in_quote = !in_quote
      out = out c
      prev = c
      continue
    }
    if (c == "#" && !in_quote && (i == 1 || prev ~ /[ \t]/)) {
      break
    }
    out = out c
    prev = c
  }
  return trim(out)
}

function parse_scalar(s) {
  s = strip_comment(s)
  if (s == "\"\"" || s == "\047\047") {
    return ""
  }
  if (s ~ /^".*"$/ || s ~ /^\047.*\047$/) {
    return substr(s, 2, length(s) - 2)
  }
  return s
}

function split_key_value(s,    idx) {
  idx = index(s, ":")
  split_key = trim(substr(s, 1, idx - 1))
  split_value = trim(substr(s, idx + 1))
}

{
  raw = $0
  if (raw ~ /^[ \t]*$/ || raw ~ /^[ \t]*#/) {
    next
  }

  first_non_space = match(raw, /[^ ]/)
  if (first_non_space == 0) {
    next
  }

  indent = first_non_space - 1
  line = substr(raw, first_non_space)

  if (index(line, ":") == 0) {
    next
  }

  split_key_value(line)
  key = split_key
  value = split_value

  if (indent == 0 && key == "settings" && strip_comment(value) == "") {
    top_section = "settings"
    settings_block = ""
    next
  }

  if (indent == 0 && key == "profiles" && strip_comment(value) == "") {
    top_section = "profiles"
    current_profile = ""
    current_block = ""
    current_category = ""
    next
  }

  if (indent == 0 && key == "default_profile") {
    default_profile = parse_scalar(value)
    next
  }

  if (top_section == "settings") {
    if (indent == 2 && key == "airgap") {
      settings["airgap"] = parse_scalar(value)
      settings_block = ""
      next
    }
    if (indent == 2 && key == "container_runtime") {
      settings["container_runtime"] = parse_scalar(value)
      settings_block = ""
      next
    }
    if (indent == 2 && key == "jq" && strip_comment(value) == "") {
      settings_block = "jq"
      next
    }
    if (indent == 2 && key == "python" && strip_comment(value) == "") {
      settings_block = "python"
      next
    }
    if (indent == 2 && key == "catalog" && strip_comment(value) == "") {
      settings_block = "catalog"
      next
    }
    if (indent == 2 && key == "container_registry" && strip_comment(value) == "") {
      settings_block = "container_registry"
      next
    }
    if (indent == 2 && key == "ci_gate" && strip_comment(value) == "") {
      settings_block = "ci_gate"
      next
    }
    if (indent == 4 && settings_block == "jq" && key == "install_url") {
      settings["jq.install_url"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "python" && key == "install_url") {
      settings["python.install_url"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "catalog" && key == "mode") {
      settings["catalog.mode"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "catalog" && key == "auth_token_env") {
      settings["catalog.auth_token_env"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "container_registry" && key == "user_env") {
      settings["container_registry.user_env"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "container_registry" && key == "password_env") {
      settings["container_registry.password_env"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "ci_gate" && key == "fail_on") {
      settings["ci_gate.fail_on"] = parse_scalar(value)
      next
    }
  }

  if (top_section != "profiles") {
    next
  }

  if (indent == 2 && value == "") {
    current_profile = key
    profile_seen[current_profile] = 1
    profile_order[++profile_count] = current_profile
    current_block = ""
    current_category = ""
    next
  }

  if (current_profile == "") {
    next
  }

  if (indent == 4 && key == "gitlab_instance") {
    profile_gitlab[current_profile] = parse_scalar(value)
    current_block = ""
    next
  }

  if (indent == 4 && key == "categories" && value == "") {
    current_block = "categories"
    current_category = ""
    next
  }

  if (current_block == "categories" && indent == 6 && value == "") {
    current_category = key
    cat_count[current_profile]++
    cat_order[current_profile, cat_count[current_profile]] = current_category
    next
  }

  if (current_block == "categories" && current_category != "" && indent == 8) {
    category_value[current_profile, current_category, key] = parse_scalar(value)
    next
  }
}

END {
  active_profile = requested_profile != "" ? requested_profile : default_profile

  print "ACTIVE_PROFILE\t" active_profile
  print "DEFAULT_PROFILE\t" default_profile
  for (i = 1; i <= profile_count; i++) {
    print "AVAILABLE_PROFILE\t" profile_order[i]
  }
  print "PROFILE_FOUND\t" (profile_seen[active_profile] ? "true" : "false")

  print "SETTING\tairgap\t" settings["airgap"]
  print "SETTING\tcontainer_runtime\t" settings["container_runtime"]
  print "SETTING\tjq.install_url\t" settings["jq.install_url"]
  print "SETTING\tpython.install_url\t" settings["python.install_url"]
  print "SETTING\tcatalog.mode\t" settings["catalog.mode"]
  print "SETTING\tcatalog.auth_token_env\t" settings["catalog.auth_token_env"]
  print "SETTING\tcontainer_registry.user_env\t" settings["container_registry.user_env"]
  print "SETTING\tcontainer_registry.password_env\t" settings["container_registry.password_env"]
  print "SETTING\tci_gate.fail_on\t" settings["ci_gate.fail_on"]

  if (profile_seen[active_profile]) {
    print "GITLAB_INSTANCE\t" profile_gitlab[active_profile]
    for (i = 1; i <= cat_count[active_profile]; i++) {
      category = cat_order[active_profile, i]
      print "CATEGORY\t" category "\tcomponent\t" category_value[active_profile, category, "component"]
      print "CATEGORY\t" category "\tversion\t" category_value[active_profile, category, "version"]
      print "CATEGORY\t" category "\timage\t" category_value[active_profile, category, "image"]
      print "CATEGORY\t" category "\trunner\t" category_value[active_profile, category, "runner"]
      print "CATEGORY\t" category "\tenabled\t" category_value[active_profile, category, "enabled"]
    }
  }
}
' "$config_path" >"$tmp_output"; then
  warn "ERROR: failed to parse config: $config_path"
  exit 1
fi

available_profiles=
active_profile=
profile_found=false
appsec_airgap=
container_runtime=
jq_install_url=
python_install_url=
catalog_mode=
catalog_auth_env=
cs_user_env=
cs_pass_env=
ci_gate_fail_on=high
gitlab_instance=

sast_component=
sast_version=
sast_image_yaml=
sast_runner=
sast_enabled=false

dependency_scanning_component=
dependency_scanning_version=
dependency_scanning_image_yaml=
dependency_scanning_runner=
dependency_scanning_enabled=false

secret_detection_component=
secret_detection_version=
secret_detection_image_yaml=
secret_detection_runner=
secret_detection_enabled=false

container_scanning_component=
container_scanning_version=
container_scanning_image_yaml=
container_scanning_runner=
container_scanning_enabled=false

category_order=
run_fortify_sast=false
run_gitlab_ds=false
run_secret_detection=false
run_gitlab_cs=false
enabled_components=

tab=$(printf '\t')
while IFS="$tab" read -r record field1 field2 field3; do
  case "$record" in
    AVAILABLE_PROFILE)
      if [ -n "$available_profiles" ]; then
        available_profiles="$available_profiles $field1"
      else
        available_profiles=$field1
      fi
      ;;
    ACTIVE_PROFILE)
      active_profile=$field1
      ;;
    PROFILE_FOUND)
      profile_found=$field1
      ;;
    SETTING)
      case "$field1" in
        airgap) appsec_airgap=$field2 ;;
        container_runtime) container_runtime=$field2 ;;
        jq.install_url) jq_install_url=$field2 ;;
        python.install_url) python_install_url=$field2 ;;
        catalog.mode) catalog_mode=$field2 ;;
        catalog.auth_token_env) catalog_auth_env=$field2 ;;
        container_registry.user_env) cs_user_env=$field2 ;;
        container_registry.password_env) cs_pass_env=$field2 ;;
        ci_gate.fail_on) [ -z "$field2" ] || ci_gate_fail_on=$field2 ;;
      esac
      ;;
    GITLAB_INSTANCE)
      gitlab_instance=$field1
      ;;
    CATEGORY)
      if [ -n "$category_order" ]; then
        case " $category_order " in
          *" $field1 "*) ;;
          *) category_order="$category_order $field1" ;;
        esac
      else
        category_order=$field1
      fi
      case "$field1:$field2" in
        sast:component) sast_component=$field3 ;;
        sast:version) sast_version=$field3 ;;
        sast:image) sast_image_yaml=$field3 ;;
        sast:runner) sast_runner=$field3 ;;
        sast:enabled) sast_enabled=$field3 ;;
        dependency_scanning:component) dependency_scanning_component=$field3 ;;
        dependency_scanning:version) dependency_scanning_version=$field3 ;;
        dependency_scanning:image) dependency_scanning_image_yaml=$field3 ;;
        dependency_scanning:runner) dependency_scanning_runner=$field3 ;;
        dependency_scanning:enabled) dependency_scanning_enabled=$field3 ;;
        secret_detection:component) secret_detection_component=$field3 ;;
        secret_detection:version) secret_detection_version=$field3 ;;
        secret_detection:image) secret_detection_image_yaml=$field3 ;;
        secret_detection:runner) secret_detection_runner=$field3 ;;
        secret_detection:enabled) secret_detection_enabled=$field3 ;;
        container_scanning:component) container_scanning_component=$field3 ;;
        container_scanning:version) container_scanning_version=$field3 ;;
        container_scanning:image) container_scanning_image_yaml=$field3 ;;
        container_scanning:runner) container_scanning_runner=$field3 ;;
        container_scanning:enabled) container_scanning_enabled=$field3 ;;
      esac
      ;;
  esac
done <"$tmp_output"

if [ "$profile_found" != "true" ]; then
  warn "ERROR: requested profile '$active_profile' not found. Available profiles: $available_profiles"
  exit 1
fi

normalized_instance=${gitlab_instance%/}
if [ "$appsec_airgap" = "true" ] && [ "$normalized_instance" = "https://gitlab.com" ]; then
  warn "ERROR: settings.airgap=true and APPSEC_PROFILE='$active_profile' targets gitlab.com; use APPSEC_PROFILE=company for an airgap-safe profile."
  exit 1
fi

append_enabled_component() {
  if [ -n "$enabled_components" ]; then
    enabled_components="$enabled_components $1|$2|$3|$4"
  else
    enabled_components="$1|$2|$3|$4"
  fi
}

apply_runner_flag() {
  category_name=$1
  runner_name=$2
  case "$runner_name" in
    fortify-sast.sh) run_fortify_sast=true ;;
    gitlab-dependency-scanning.sh) run_gitlab_ds=true ;;
    secret-detection.sh) run_secret_detection=true ;;
    gitlab-container-scanning.sh) run_gitlab_cs=true ;;
    none) ;;
    *)
      warn "WARNING: unknown runner $runner_name for category $category_name — no RUN_ flag set"
      ;;
  esac
}

# Resolved before the loop: ENABLED_COMPONENTS carries the effective image so
# catalog.sh check-drift can compare the component's declared image against the
# one that actually runs. Env overrides win — they are what executes.
if [ -n "${FORTIFY_SAST_IMAGE:-}" ]; then
  fortify_sast_image=$FORTIFY_SAST_IMAGE
else
  fortify_sast_image=$sast_image_yaml
fi

if [ -n "${SECRET_DETECTION_IMAGE:-}" ]; then
  secret_detection_image=$SECRET_DETECTION_IMAGE
else
  secret_detection_image=$secret_detection_image_yaml
fi

if [ -n "${GITLAB_DS_IMAGE:-}" ]; then
  gitlab_ds_image=$GITLAB_DS_IMAGE
else
  gitlab_ds_image=$dependency_scanning_image_yaml
fi

if [ -n "${GITLAB_CS_IMAGE:-}" ]; then
  gitlab_cs_image=$GITLAB_CS_IMAGE
else
  gitlab_cs_image=$container_scanning_image_yaml
fi

for category_name in $category_order; do
  category_component=
  category_version=
  category_runner=
  category_image=
  category_enabled=false

  case "$category_name" in
    sast)
      category_component=$sast_component
      category_version=$sast_version
      category_runner=$sast_runner
      category_image=$fortify_sast_image
      category_enabled=$sast_enabled
      ;;
    dependency_scanning)
      category_component=$dependency_scanning_component
      category_version=$dependency_scanning_version
      category_runner=$dependency_scanning_runner
      category_image=$gitlab_ds_image
      category_enabled=$dependency_scanning_enabled
      ;;
    secret_detection)
      category_component=$secret_detection_component
      category_version=$secret_detection_version
      category_runner=$secret_detection_runner
      category_image=$secret_detection_image
      category_enabled=$secret_detection_enabled
      ;;
    container_scanning)
      category_component=$container_scanning_component
      category_version=$container_scanning_version
      category_runner=$container_scanning_runner
      category_image=$gitlab_cs_image
      category_enabled=$container_scanning_enabled
      ;;
  esac

  if [ "$category_enabled" = "true" ]; then
    apply_runner_flag "$category_name" "$category_runner"
    if [ -n "$category_component" ] && [ -n "$category_version" ] && [ -n "$category_runner" ]; then
      append_enabled_component "$category_component" "$category_version" "$category_runner" "$category_image"
    fi
  fi
done


emit APPSEC_PROFILE "$active_profile"
emit APPSEC_AIRGAP "$appsec_airgap"
emit CONTAINER_RUNTIME "$container_runtime"
emit JQ_INSTALL_URL "$jq_install_url"
emit PYTHON_INSTALL_URL "$python_install_url"
emit CATALOG_MODE "$catalog_mode"
emit CATALOG_AUTH_ENV "$catalog_auth_env"
emit CS_USER_ENV "$cs_user_env"
emit CS_PASS_ENV "$cs_pass_env"
emit CI_GATE_FAIL_ON "$ci_gate_fail_on"
emit GITLAB_INSTANCE "$gitlab_instance"
emit FORTIFY_SAST_IMAGE "$fortify_sast_image"
emit SECRET_DETECTION_IMAGE "$secret_detection_image"
emit GITLAB_DS_IMAGE "$gitlab_ds_image"
emit GITLAB_CS_IMAGE "$gitlab_cs_image"
emit RUN_FORTIFY_SAST "$run_fortify_sast"
emit RUN_GITLAB_DS "$run_gitlab_ds"
emit RUN_SECRET_DETECTION "$run_secret_detection"
emit RUN_GITLAB_CS "$run_gitlab_cs"
emit ENABLED_COMPONENTS "$enabled_components"

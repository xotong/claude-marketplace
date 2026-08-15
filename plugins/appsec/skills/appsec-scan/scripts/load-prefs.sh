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
#   - settings.ca_bundle
#   - settings.pip_index_url
#   - settings.maven_settings
#   - settings.jq.install_url
#   - settings.python.install_url
#   - settings.catalog.auth_token_env
#   - settings.build_credentials.artifactory_user_env
#   - settings.build_credentials.artifactory_password_env
#   - settings.container_registry.user_env
#   - settings.container_registry.password_env
#   - settings.container_registry.base_repo
#   - settings.container_registry.hardened_repo
#   - settings.ci_gate.fail_on
#   - default_profile
#   - profiles.<name>.gitlab_instance
#   - profiles.<name>.{auth_token_env,base_repo,hardened_repo}   (override the global)
#   - profiles.<name>.categories.<category>.{component,version,image,runner,enabled}
#
# Config key -> exported name, for whoever wires a new key into a runner:
#   ca_bundle                        -> CA_BUNDLE          (host path; mounted, then
#                                       exported inside the container as
#                                       ADDITIONAL_CA_CERT_BUNDLE)
#   pip_index_url                    -> APPSEC_PIP_INDEX_URL
#   maven_settings                   -> MAVEN_SETTINGS     (already read by
#                                       scanners/fortify-sast.sh)
#   container_registry.base_repo     -> BASE_IMAGE_REPO
#   container_registry.hardened_repo -> HARDENED_IMAGE_REPO (suggestion-only)
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
  sub(/^[ \t\r]+/, "", s)
  sub(/[ \t\r]+$/, "", s)
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
  # Normalize one mixed-CRLF line before indentation or scalar comparisons can
  # silently disable the scanner declared on that line.
  sub(/\r$/, "")
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
    if (indent == 2 && key == "image_policy") {
      settings["image_policy"] = parse_scalar(value)
      settings_block = ""
      next
    }
    # Airgap plumbing. Each one clears settings_block for the same reason the
    # scalars above do: leaving a stale block name set would let the NEXT
    # indent-4 key be filed under the previous block.
    if (indent == 2 && key == "ca_bundle") {
      settings["ca_bundle"] = parse_scalar(value)
      settings_block = ""
      next
    }
    if (indent == 2 && key == "pip_index_url") {
      settings["pip_index_url"] = parse_scalar(value)
      settings_block = ""
      next
    }
    if (indent == 2 && key == "maven_settings") {
      settings["maven_settings"] = parse_scalar(value)
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
    if (indent == 2 && key == "package_registries" && strip_comment(value) == "") {
      settings_block = "package_registries"
      next
    }
    if (indent == 4 && settings_block == "package_registries") {
      settings["package_registries." key] = parse_scalar(value)
      next
    }
    if (indent == 2 && key == "python_runtime" && strip_comment(value) == "") {
      settings_block = "python_runtime"
      next
    }
    if (indent == 4 && settings_block == "python_runtime") {
      settings["python_runtime." key] = parse_scalar(value)
      next
    }
    if (indent == 2 && key == "build_credentials" && strip_comment(value) == "") {
      settings_block = "build_credentials"
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
    if (indent == 4 && settings_block == "catalog" && key == "auth_token_env") {
      settings["catalog.auth_token_env"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "build_credentials" && key == "artifactory_user_env") {
      settings["build_credentials.artifactory_user_env"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "build_credentials" && key == "artifactory_password_env") {
      settings["build_credentials.artifactory_password_env"] = parse_scalar(value)
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
    if (indent == 4 && settings_block == "container_registry" && key == "base_repo") {
      settings["container_registry.base_repo"] = parse_scalar(value)
      next
    }
    if (indent == 4 && settings_block == "container_registry" && key == "hardened_repo") {
      settings["container_registry.hardened_repo"] = parse_scalar(value)
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

  if (indent == 2 && strip_comment(value) == "") {
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

  # auth_token_env is a property of the INSTANCE, so it belongs with
  # gitlab_instance. A profile-level value (including an explicit "") overrides
  # settings.catalog.auth_token_env; without one the global default applies.
  if (indent == 4 && key == "auth_token_env") {
    profile_auth[current_profile] = parse_scalar(value)
    profile_auth_set[current_profile] = 1
    current_block = ""
    next
  }

  # base_repo / hardened_repo are properties of the registry this profile talks
  # to, so like auth_token_env they override the global default — including an
  # explicit "", which is how a profile turns an inherited probe back off.
  if (indent == 4 && key == "base_repo") {
    profile_base_repo[current_profile] = parse_scalar(value)
    profile_base_repo_set[current_profile] = 1
    current_block = ""
    next
  }

  if (indent == 4 && key == "hardened_repo") {
    profile_hardened_repo[current_profile] = parse_scalar(value)
    profile_hardened_repo_set[current_profile] = 1
    current_block = ""
    next
  }

  if (indent == 4 && key == "categories" && strip_comment(value) == "") {
    current_block = "categories"
    current_category = ""
    next
  }

  if (current_block == "categories" && indent == 6) {
    # Clear the prior slot before interpreting every category-level key so a
    # typo can never graft its nested settings onto the preceding scanner.
    current_category = ""
    if (key !~ /^(sast|dependency_scanning|secret_detection|container_scanning)$/) {
      print "PARSER_WARNING\tWARNING: unknown category key \047" key "\047 in profile \047" current_profile "\047"
      next
    }
    if (strip_comment(value) == "") {
      current_category = key
      cat_count[current_profile]++
      cat_order[current_profile, cat_count[current_profile]] = current_category
    }
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
  print "SETTING\tca_bundle\t" settings["ca_bundle"]
  print "SETTING\tpip_index_url\t" settings["pip_index_url"]
  print "SETTING\tmaven_settings\t" settings["maven_settings"]
  print "SETTING\tcontainer_registry.base_repo\t" settings["container_registry.base_repo"]
  print "SETTING\tcontainer_registry.hardened_repo\t" settings["container_registry.hardened_repo"]
  print "SETTING\tjq.install_url\t" settings["jq.install_url"]
  print "SETTING\tpython.install_url\t" settings["python.install_url"]
  print "SETTING\tcatalog.auth_token_env\t" settings["catalog.auth_token_env"]
  print "SETTING\tpython_runtime.uv_version\t" settings["python_runtime.uv_version"]
  print "SETTING\tpython_runtime.uv_installer_base\t" settings["python_runtime.uv_installer_base"]
  print "SETTING\tpython_runtime.uv_python_install_mirror\t" settings["python_runtime.uv_python_install_mirror"]
  print "SETTING\tpython_runtime.python_version\t" settings["python_runtime.python_version"]
  print "SETTING\tbuild_credentials.artifactory_user_env\t" settings["build_credentials.artifactory_user_env"]
  print "SETTING\tbuild_credentials.artifactory_password_env\t" settings["build_credentials.artifactory_password_env"]
  print "SETTING\tcontainer_registry.user_env\t" settings["container_registry.user_env"]
  print "SETTING\tcontainer_registry.password_env\t" settings["container_registry.password_env"]
  print "SETTING\tci_gate.fail_on\t" settings["ci_gate.fail_on"]
  print "SETTING\timage_policy\t" settings["image_policy"]
  print "SETTING\tpackage_registries.npm\t" settings["package_registries.npm"]
  print "SETTING\tpackage_registries.pypi\t" settings["package_registries.pypi"]
  print "SETTING\tpackage_registries.maven\t" settings["package_registries.maven"]
  print "SETTING\tpackage_registries.go\t" settings["package_registries.go"]
  print "SETTING\tpackage_registries.auth_token_env\t" settings["package_registries.auth_token_env"]

  if (profile_seen[active_profile]) {
    print "GITLAB_INSTANCE\t" profile_gitlab[active_profile]
    if (profile_auth_set[active_profile]) {
      print "PROFILE_AUTH_TOKEN_ENV\t" profile_auth[active_profile]
    }
    if (profile_base_repo_set[active_profile]) {
      print "PROFILE_BASE_REPO\t" profile_base_repo[active_profile]
    }
    if (profile_hardened_repo_set[active_profile]) {
      print "PROFILE_HARDENED_REPO\t" profile_hardened_repo[active_profile]
    }
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
catalog_auth_env=
ca_bundle=
pip_index_url=
maven_settings=
# Default to the names the CI component itself uses, so an estate that already
# sets those needs no config at all.
uv_version=
uv_installer_base=
uv_python_install_mirror=
fortify_python_version=
artifactory_user_env=ARTIFACTORY_USER
artifactory_password_env=ARTIFACTORY_PASSWORD
cs_user_env=
cs_pass_env=
base_image_repo=
hardened_image_repo=
ci_gate_fail_on=high
image_policy=follow-component
pkg_reg_npm=
pkg_reg_pypi=
pkg_reg_maven=
pkg_reg_go=
pkg_reg_auth_env=
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
        catalog.auth_token_env) catalog_auth_env=$field2 ;;
        ca_bundle) ca_bundle=$field2 ;;
        pip_index_url) pip_index_url=$field2 ;;
        maven_settings) maven_settings=$field2 ;;
        python_runtime.uv_version) uv_version=$field2 ;;
        python_runtime.uv_installer_base) uv_installer_base=$field2 ;;
        python_runtime.uv_python_install_mirror) uv_python_install_mirror=$field2 ;;
        python_runtime.python_version) fortify_python_version=$field2 ;;
        build_credentials.artifactory_user_env) [ -z "$field2" ] || artifactory_user_env=$field2 ;;
        build_credentials.artifactory_password_env) [ -z "$field2" ] || artifactory_password_env=$field2 ;;
        container_registry.user_env) cs_user_env=$field2 ;;
        container_registry.password_env) cs_pass_env=$field2 ;;
        container_registry.base_repo) base_image_repo=$field2 ;;
        container_registry.hardened_repo) hardened_image_repo=$field2 ;;
        ci_gate.fail_on) [ -z "$field2" ] || ci_gate_fail_on=$field2 ;;
        image_policy) [ -z "$field2" ] || image_policy=$field2 ;;
        package_registries.npm) pkg_reg_npm=$field2 ;;
        package_registries.pypi) pkg_reg_pypi=$field2 ;;
        package_registries.maven) pkg_reg_maven=$field2 ;;
        package_registries.go) pkg_reg_go=$field2 ;;
        package_registries.auth_token_env) pkg_reg_auth_env=$field2 ;;
      esac
      ;;
    PROFILE_AUTH_TOKEN_ENV)
      catalog_auth_env=$field1
      ;;
    PROFILE_BASE_REPO)
      base_image_repo=$field1
      ;;
    PROFILE_HARDENED_REPO)
      hardened_image_repo=$field1
      ;;
    GITLAB_INSTANCE)
      gitlab_instance=$field1
      ;;
    PARSER_WARNING)
      warn "$field1"
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
  warn "ERROR: settings.airgap=true and APPSEC_PROFILE='$active_profile' targets gitlab.com; select a profile whose gitlab_instance is your internal instance."
  exit 1
fi

# Tuple: component|version|runner|image|category
# The category is last so the three fields every consumer already reads keep
# their positions. Consumers that want the image must take field 4 with
# "${rest%%|*}", not the trailing "${rest#*|}" — the latter now swallows the
# category too.
append_enabled_component() {
  if [ -n "$enabled_components" ]; then
    enabled_components="$enabled_components $1|$2|$3|$4|$5"
  else
    enabled_components="$1|$2|$3|$4|$5"
  fi
}

# runner: is optional. Each category has exactly one shipped runner, so the
# common config carries only component/version/enabled. Declaring it stays
# supported for a custom or swapped runner, and check-drift uses the name to
# locate the sibling <runner>.contract.
default_runner_for() {
  case "$1" in
    sast)                printf 'fortify-sast.sh' ;;
    dependency_scanning) printf 'gitlab-dependency-scanning.sh' ;;
    secret_detection)    printf 'secret-detection.sh' ;;
    container_scanning)  printf 'gitlab-container-scanning.sh' ;;
  esac
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

# MAVEN_SETTINGS predates settings.maven_settings — run-scan.sh and
# fortify-sast.sh already read it from the ambient environment. Emitting the
# shipped empty default unconditionally would silently unset a working export
# and send the maven build back to the public central repo, so an existing
# value wins here exactly as it does for the *_IMAGE overrides above.
if [ -n "${MAVEN_SETTINGS:-}" ]; then
  maven_settings=$MAVEN_SETTINGS
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
    [ -n "$category_runner" ] || category_runner=$(default_runner_for "$category_name")
    apply_runner_flag "$category_name" "$category_runner"
    if [ -n "$category_component" ] && [ -n "$category_version" ] && [ -n "$category_runner" ]; then
      append_enabled_component "$category_component" "$category_version" "$category_runner" "$category_image" "$category_name"
    fi
  fi
done


emit APPSEC_PROFILE "$active_profile"
emit APPSEC_AIRGAP "$appsec_airgap"
emit CONTAINER_RUNTIME "$container_runtime"
emit JQ_INSTALL_URL "$jq_install_url"
emit PYTHON_INSTALL_URL "$python_install_url"
emit CATALOG_AUTH_ENV "$catalog_auth_env"
emit CA_BUNDLE "$ca_bundle"
# Deliberately NOT named PIP_INDEX_URL. These assignments get eval'd into the
# caller's own shell, and pip reads PIP_INDEX_URL directly — exporting the
# shipped empty default would point the developer's own pip at an empty index
# and break every unrelated `pip install` in that terminal.
emit APPSEC_PIP_INDEX_URL "$pip_index_url"
emit MAVEN_SETTINGS "$maven_settings"
emit UV_VERSION "$uv_version"
emit UV_INSTALLER_BASE "$uv_installer_base"
emit UV_PYTHON_INSTALL_MIRROR "$uv_python_install_mirror"
emit FORTIFY_PYTHON_VERSION "$fortify_python_version"
emit ARTIFACTORY_USER_ENV "$artifactory_user_env"
emit ARTIFACTORY_PASSWORD_ENV "$artifactory_password_env"
emit CS_USER_ENV "$cs_user_env"
emit CS_PASS_ENV "$cs_pass_env"
emit BASE_IMAGE_REPO "$base_image_repo"
# Suggestion-only: a hardened image is a different image, not a newer tag, so
# this must never feed a status decision or the fix loop. See the config comment.
emit HARDENED_IMAGE_REPO "$hardened_image_repo"
emit CI_GATE_FAIL_ON "$ci_gate_fail_on"
emit IMAGE_POLICY "$image_policy"
emit PACKAGE_REGISTRY_AUTH_ENV "$pkg_reg_auth_env"
emit PACKAGE_REGISTRIES "$(printf '{"npm":"%s","pypi":"%s","maven":"%s","go":"%s"}' \
  "$pkg_reg_npm" "$pkg_reg_pypi" "$pkg_reg_maven" "$pkg_reg_go")"
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

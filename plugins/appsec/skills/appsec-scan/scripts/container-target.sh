#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <runtime> <app_name> <results_dir>" >&2
  printf 'error|usage\n'
  exit 2
fi

runtime=$1
app_name=$2
results_dir=$3
image_ref="appsec-local/${app_name}:appsec-scan"
build_log="${results_dir}/container-build.log"
archive_path="${results_dir}/container-image.tar"
base_images_path="${results_dir}/base-images.json"
dockerfile_path=""

mkdir -p "${results_dir}"

# -----------------------------------------------------------------------------
# Best-effort FROM-line inventory, written regardless of scan mode.
#
# No jq/python3 here on purpose: both are optional in this skill (see
# resolve-jq.sh / resolve-python.sh), and no bash 4 features (associative
# arrays, ${var,,}) either — the bash on PATH in this environment is macOS's
# stock 3.2, which has neither. Lookups below use linear scans over parallel
# indexed arrays instead of maps, and case-insensitive [[Ss]][[Cc]]... regexes
# instead of case-conversion expansion — also keeps this script running on a
# PATH stripped down to a handful of tools (no guaranteed `tr`).
# -----------------------------------------------------------------------------

# ARG name -> default value, in declaration order (parallel arrays; bash 3.2
# has no associative arrays).
ARG_NAMES=()
ARG_VALUES=()
# Stage names introduced by `AS <alias>` on FROM lines seen so far.
ALIAS_NAMES=()
# JSON object strings, one per recorded external base image.
ENTRIES=()

# Escapes a value for use inside a JSON string literal. Dockerfile FROM
# arguments are single tokens (no embedded newlines), so only backslash and
# quote need handling — but ARG defaults are free text, so both are escaped
# defensively rather than assumed clean.
json_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  printf '%s' "$s"
}

arg_lookup() {
  local name=$1 i
  for ((i = 0; i < ${#ARG_NAMES[@]}; i++)); do
    if [[ "${ARG_NAMES[$i]}" == "$name" ]]; then
      printf '%s' "${ARG_VALUES[$i]}"
      return 0
    fi
  done
  return 1
}

is_known_alias() {
  local name=$1 i
  for ((i = 0; i < ${#ALIAS_NAMES[@]}; i++)); do
    if [[ "${ALIAS_NAMES[$i]}" == "$name" ]]; then
      return 0
    fi
  done
  return 1
}

# Best-effort ${VAR}/$VAR substitution using ARG defaults seen earlier in the
# file. Sets RESOLVED_REF and RESOLVED_OK. RESOLVED_OK=0 means a $VAR survived
# substitution (no matching ARG, or the ARG has no default) — the caller must
# skip the FROM rather than emit a base image name we invented.
resolve_ref() {
  local rest=$1 out="" matched name val
  RESOLVED_OK=1
  while [[ "$rest" =~ \$(\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*) ]]; do
    matched="${BASH_REMATCH[0]}"
    out+="${rest%%"$matched"*}"
    name=${matched#\$}
    name=${name#\{}
    name=${name%\}}
    if val=$(arg_lookup "$name"); then
      out+="$val"
    else
      RESOLVED_OK=0
      break
    fi
    rest="${rest#*"$matched"}"
  done
  [[ "$RESOLVED_OK" -eq 1 ]] && out+="$rest"
  RESOLVED_REF="$out"
}

# Splits a resolved (ARG-free) ref into IMAGE_NAME (registry/namespace
# stripped) and IMAGE_TAG (default "latest", or the digest for @sha256 refs).
# A colon only means "tag" in the final /-segment — `registry:5000/ns/img`
# has a port, not a tag, so the naive "split on the first colon" approach
# would mis-parse the port as a tag.
parse_image_tag() {
  local ref=$1 repo tag last_segment
  if [[ "$ref" == *@* ]]; then
    tag=${ref#*@}
    repo=${ref%%@*}
  else
    last_segment=${ref##*/}
    if [[ "$last_segment" == *:* ]]; then
      tag=${ref##*:}
      repo=${ref%:*}
    else
      tag="latest"
      repo=$ref
    fi
  fi
  IMAGE_NAME=${repo##*/}
  IMAGE_TAG=$tag
}

append_base_image_entry() {
  local raw=$1 image=$2 tag=$3 line=$4 alias=$5
  ENTRIES+=("{\"raw\":\"$(json_escape "$raw")\",\"image\":\"$(json_escape "$image")\",\"tag\":\"$(json_escape "$tag")\",\"line\":${line},\"alias\":\"$(json_escape "$alias")\"}")
}

write_base_images_json() {
  local out=$1
  if [[ ${#ENTRIES[@]} -eq 0 ]]; then
    printf '[]\n' >"$out"
    return
  fi
  {
    printf '[\n'
    local i last=$((${#ENTRIES[@]} - 1))
    for ((i = 0; i < ${#ENTRIES[@]}; i++)); do
      if [[ $i -eq $last ]]; then
        printf '  %s\n' "${ENTRIES[$i]}"
      else
        printf '  %s,\n' "${ENTRIES[$i]}"
      fi
    done
    printf ']\n'
  } >"$out"
}

# Parses FROM instructions out of a Dockerfile into ENTRIES, then writes
# base-images.json. Always writes the file — [] when there is no Dockerfile
# or it names nothing external — so a consumer can tell "looked, found none"
# apart from "never ran".
write_base_images() {
  local dockerfile=$1 out=$2
  ENTRIES=()
  ARG_NAMES=()
  ARG_VALUES=()
  ALIAS_NAMES=()

  if [[ -n "$dockerfile" && -f "$dockerfile" ]]; then
    local lineno=0 line
    while IFS= read -r line || [[ -n "$line" ]]; do
      lineno=$((lineno + 1))

      if [[ "$line" =~ ^[[:space:]]*[Aa][Rr][Gg][[:space:]]+([A-Za-z_][A-Za-z0-9_]*)(=(.*))?[[:space:]]*$ ]]; then
        local arg_name=${BASH_REMATCH[1]} arg_val=${BASH_REMATCH[3]}
        if [[ -n "${BASH_REMATCH[2]}" ]]; then
          if [[ "$arg_val" =~ ^\"(.*)\"$ || "$arg_val" =~ ^\'(.*)\'$ ]]; then
            arg_val=${BASH_REMATCH[1]}
          fi
          ARG_NAMES+=("$arg_name")
          ARG_VALUES+=("$arg_val")
        fi
        continue
      fi

      if [[ "$line" =~ ^[[:space:]]*[Ff][Rr][Oo][Mm][[:space:]]+(.+)$ ]]; then
        local remainder=${BASH_REMATCH[1]}
        local tokens=()
        read -ra tokens <<<"$remainder"

        local idx=0
        while [[ "${tokens[idx]:-}" == --* ]]; do
          idx=$((idx + 1))
        done
        local raw_ref=${tokens[idx]:-}
        idx=$((idx + 1))
        local alias=""
        if [[ "${tokens[idx]:-}" =~ ^[Aa][Ss]$ ]]; then
          alias=${tokens[idx + 1]:-}
        fi

        if [[ -n "$raw_ref" ]]; then
          resolve_ref "$raw_ref"

          if [[ "$RESOLVED_OK" -eq 1 && ! "$RESOLVED_REF" =~ ^[Ss][Cc][Rr][Aa][Tt][Cc][Hh]$ ]] \
            && ! is_known_alias "$RESOLVED_REF"; then
            parse_image_tag "$RESOLVED_REF"
            append_base_image_entry "$raw_ref" "$IMAGE_NAME" "$IMAGE_TAG" "$lineno" "$alias"
          fi
        fi

        # A later stage may reference this alias (`FROM build AS final`) — that's
        # an internal stage reference, not an external image, so it must be
        # recognized even when this FROM itself was skipped (e.g. `FROM scratch
        # AS base`).
        [[ -n "$alias" ]] && ALIAS_NAMES+=("$alias")
      fi
    done <"$dockerfile"
  fi

  write_base_images_json "$out"
}

# Dockerfile discovery runs unconditionally, before the CS_IMAGE early return
# below. It used to sit after that return, so a registry-mode run (CS_IMAGE
# set) never looked for a Dockerfile at all and base-images.json was never
# written for that path. Not finding one here is normal in registry mode and
# must not affect the mode|value contract on stdout or the exit status.
if [[ -n "${DOCKERFILE:-}" && -f "${DOCKERFILE}" ]]; then
  dockerfile_path=${DOCKERFILE}
elif [[ -f ./Dockerfile ]]; then
  dockerfile_path=./Dockerfile
else
  while IFS= read -r match; do
    dockerfile_path=${match}
    break
  done < <(
    find . \
      -maxdepth 3 \
      -type d \( -name '.git' -o -name 'node_modules' \) -prune -o \
      -type f \( -name 'Dockerfile' -o -name '*.Dockerfile' \) -print
  )
fi

write_base_images "${dockerfile_path}" "${base_images_path}"

if [[ -n "${CS_IMAGE:-}" ]]; then
  printf 'registry|%s\n' "${CS_IMAGE}"
  exit 0
fi

if [[ -z "${dockerfile_path}" ]]; then
  echo "INFO: no Dockerfile and CS_IMAGE unset — container scanning will be deferred to CI" >&2
  printf 'none|\n'
  exit 0
fi

dockerfile_dir=$(dirname "${dockerfile_path}")
: > "${build_log}"

if ! "${runtime}" build -t "${image_ref}" -f "${dockerfile_path}" "${dockerfile_dir}" >"${build_log}" 2>&1; then
  if grep -qiE 'pull access denied|unauthorized|manifest unknown|no basic auth|not found: manifest|denied: requested access' "${build_log}"; then
    cat >&2 <<EOF
Container image build failed because the Dockerfile base image could not be pulled from the internal registry.

Fix:
1. ${runtime} login <your-registry-host> with your JFrog creds, or set the registry credential env vars named in scanner-preferences.yaml settings.container_registry (CS_REGISTRY_USER / CS_REGISTRY_PASSWORD).
2. Ensure the Dockerfile FROM points at the internal mirror.

Then re-run the scan.
EOF
    printf 'error|base-pull\n'
    exit 3
  fi

  echo "Container image build failed. Submit a Jira ticket under others." >&2
  echo "see ${build_log}" >&2
  printf 'error|build\n'
  exit 3
fi

if ! "${runtime}" save "${image_ref}" -o "${archive_path}" >>"${build_log}" 2>&1; then
  echo "Container image build failed. Submit a Jira ticket under others." >&2
  echo "see ${build_log}" >&2
  printf 'error|save\n'
  exit 3
fi

printf 'archive|%s\n' "${archive_path}"

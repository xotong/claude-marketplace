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
dockerfile_path=""

mkdir -p "${results_dir}"

if [[ -n "${CS_IMAGE:-}" ]]; then
  printf 'registry|%s\n' "${CS_IMAGE}"
  exit 0
fi

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

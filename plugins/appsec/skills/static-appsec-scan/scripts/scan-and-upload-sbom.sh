#!/bin/bash
#
# scan-and-upload-sbom.sh — Run local dependency scan, upload SBOM to remote repo, trigger pipeline, and download report
#
# Usage:
#   ./scan-and-upload-sbom.sh [--language <lang>] [--source-path <path>] [--services <json>]
#
# This script:
# 1. Runs glci dependency-scanning locally to generate SBOM
# 2. Uploads SBOM to remote-dependency-scanning package registry
# 3. Triggers the remote pipeline via CI/CD trigger token
# 4. Polls for pipeline completion
# 5. Downloads the vulnerability report
#
# Multi-service support:
#   --services JSON array of {"path": "...", "language": "...", "manifest": "..."}
#   Scans each service directory separately and merges findings
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration - loaded from scanner-preferences.yaml or defaults
GITLAB_URL="https://gitlab.<YOUR_GITLAB_INSTANCE>"
SBOM_PROJECT_ID="<YOUR_PROJECT_ID>"  # pipeline-component/remote-dependency-scanning
REMOTE_PROJECT_ID="<YOUR_PROJECT_ID>"
GITLAB_TOKEN="<YOUR_GITLAB_TOKEN>"
POLL_INTERVAL="${REMOTE_SBOM_POLL_INTERVAL:-15}"
TIMEOUT="${REMOTE_SBOM_TIMEOUT:-600}"

# Default values
LANGUAGE="${LANGUAGE:-}"
SOURCE_PATH="${SOURCE_PATH:-.}"
SERVICES_JSON="${SERVICES_JSON:-}"
PROJECT_ROOT="$(pwd)"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --language)
      LANGUAGE="$2"
      shift 2
      ;;
    --source-path)
      SOURCE_PATH="$2"
      shift 2
      ;;
    --services)
      SERVICES_JSON="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --poll-interval)
      POLL_INTERVAL="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--language <lang>] [--source-path <path>] [--services <json>] [--project-root <path>]"
      echo ""
      echo "Options:"
      echo "  --language        Programming language for SBOM generation: javascript, java, python, go, maven, gradle"
      echo "  --source-path     Path to source code (default: .)"
      echo "  --services        JSON array of services to scan: [{\"path\":\"...\",\"language\":\"...\",\"manifest\":\"...\"}]"
      echo "  --project-root    Root directory of the project (default: pwd)"
      echo "  --poll-interval   Polling interval in seconds (default: 15)"
      echo "  --timeout         Maximum wait time in seconds (default: 600)"
      echo "  -h, --help        Show this help message"
      echo ""

      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      exit 1
      ;;
  esac
done




# Generate unique identifier with datetime and username
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
USERNAME=$(whoami)
BASE_SCAN_ID="scan-${TIMESTAMP}-${USERNAME}"

ARTIFACTS_DIR="glci-artifacts"
mkdir -p "${ARTIFACTS_DIR}"

# Check if glci is available
if ! command -v glci &>/dev/null; then
  echo "ERROR: glci binary not found in PATH" >&2
  exit 1
fi

# Function to scan all services - runs glci once, then triggers remote pipeline for each SBOM
scan_all_services() {
  local BASE_SCAN_ID="${BASE_SCAN_ID}"
  local PIPELINE_FILE="${PROJECT_ROOT}/local-pipeline.yml"

  echo ""
  echo "=== Multi-Service Dependency Scan ==="
  echo "Project root: ${PROJECT_ROOT}"
  echo ""

  # Always run glci from project root
  cd "${PROJECT_ROOT}"

  # Copy standard pipeline template if local-pipeline.yml doesn't exist
  if [[ ! -f "$PIPELINE_FILE" ]]; then
    echo "Creating local-pipeline.yml from template..."
    cp "$SKILL_DIR/reference/std-pipeline.yml" "$PIPELINE_FILE"
  fi

  # Ensure GITLAB_FEATURES is set for dependency scanning
  if ! grep -q "GITLAB_FEATURES" "$PIPELINE_FILE"; then
    if grep -q "^variables:" "$PIPELINE_FILE"; then
      sed -i '/^variables:/a\  GITLAB_FEATURES: "dependency_scanning"' "$PIPELINE_FILE"
    else
      sed -i '/^stages:/a\\nvariables:\n  GITLAB_FEATURES: "dependency_scanning"' "$PIPELINE_FILE"
    fi
    echo "Added GITLAB_FEATURES to $PIPELINE_FILE"
  fi

  # Ensure dependency-scanning component is included
  if ! grep -q "dependency-scanning" "$PIPELINE_FILE"; then
    echo "Adding dependency-scanning component to pipeline..."
    cat >> "$PIPELINE_FILE" << 'EOF'

# Dependency scanning component
include:
  - component: $CI_SERVER_FQDN/pipeline-component/dependency-scanning/dependency-scanning@1.0.2
    inputs:
      stage: scans
      language: javascript
EOF
    echo "Added dependency-scanning component to $PIPELINE_FILE"
  fi

  # Step 1: Run glci dependency scan ONCE to get all SBOMs
  echo "Step 1/4: Running dependency scan to generate SBOMs for all services..."
  echo ""
  echo "Note: The glci job may report failure - this is expected. We only need the SBOM artifacts."
  echo ""

  set +e
  GLCI_OUTPUT=$(glci -f "$PIPELINE_FILE" run dependency-scanning --context "branch=main" --gitlab-url "$GITLAB_URL" --token "$GITLAB_TOKEN" 2>&1)
  GLCI_EXIT_CODE=$?
  set -e

  echo "$GLCI_OUTPUT"
  echo ""

  # Check if no jobs matched
  if echo "$GLCI_OUTPUT" | grep -qi "no jobs to run\|none matched"; then
    echo "Re-running dependency scan with updated pipeline..."
    echo ""
    set +e
    GLCI_OUTPUT=$(glci -f "$PIPELINE_FILE" run dependency-scanning --context "branch=main" --gitlab-url "$GITLAB_URL" --token "$GITLAB_TOKEN" 2>&1)
    set -e
    echo "$GLCI_OUTPUT"
    echo ""
  fi

  # Download SBOM artifacts
  echo ""
  echo "Downloading SBOM artifacts from glci..."
  set +e
  glci artifacts download dependency-scanning --output "${ARTIFACTS_DIR}" 2>&1
  set -e

  # Unzip and extract all SBOMs
  ZIP_FILE="${ARTIFACTS_DIR}/dependency-scanning.zip"
  if [[ -f "$ZIP_FILE" ]]; then
    echo "Extracting dependency-scanning.zip..."
    TEMP_EXTRACT_DIR="${ARTIFACTS_DIR}/.tmp-extract"
    mkdir -p "$TEMP_EXTRACT_DIR"
    unzip -o "$ZIP_FILE" -d "$TEMP_EXTRACT_DIR" >&2
    # Flatten: move all .cdx.json files to artifacts root
    find "$TEMP_EXTRACT_DIR" -name "*.cdx.json" -exec mv {} "${ARTIFACTS_DIR}/" \;
    rm -rf "$TEMP_EXTRACT_DIR"
    rm -f "$ZIP_FILE"
  fi

  # Collect all SBOM files
  mapfile -t SBOM_FILES < <(find "${ARTIFACTS_DIR}" -maxdepth 1 -name "gl-sbom-*.cdx.json" -type f 2>/dev/null)

  if [[ ${#SBOM_FILES[@]} -eq 0 ]]; then
    echo "ERROR: No SBOM files found in ${ARTIFACTS_DIR}" >&2
    return 1
  fi

  echo ""
  echo "Found ${#SBOM_FILES[@]} SBOM file(s):"
  for sbom in "${SBOM_FILES[@]}"; do
    echo "  - $(basename "$sbom")"
  done
  echo ""

  # Step 2 & 3: For EACH SBOM, upload and trigger remote pipeline separately
  echo "Step 2/4 & 3/4: Uploading SBOMs and triggering remote pipeline for each..."
  echo ""

  declare -a PIPELINE_IDS=()
  declare -a REPORT_FILES=()
  SBOM_INDEX=0

  for SBOM_FILE_PATH in "${SBOM_FILES[@]}"; do
    SBOM_FILE_NAME="$(basename "$SBOM_FILE_PATH")"
    # Extract language from SBOM filename (e.g., gl-sbom-npm-npm.cdx.json -> npm)
    SBOM_LANG=$(echo "$SBOM_FILE_NAME" | sed 's/gl-sbom-\([^.-]*\).*/\1/')
    SCAN_ID="${BASE_SCAN_ID}-sbom-${SBOM_INDEX}-${SBOM_LANG}"

    echo "--- Processing: ${SBOM_FILE_NAME} (${SBOM_LANG}) ---"

    # Upload SBOM
    echo "  Uploading SBOM to registry..."
    UPLOAD_RESPONSE=$(curl --silent --show-error --write-out "\n%{http_code}" --request PUT \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      --header "Content-Type: application/json" \
      --upload-file "${SBOM_FILE_PATH}" \
      "${GITLAB_URL}/api/v4/projects/${SBOM_PROJECT_ID}/packages/generic/local-sboms/${SCAN_ID}/${SBOM_FILE_NAME}")

    UPLOAD_HTTP_CODE=$(echo "$UPLOAD_RESPONSE" | tail -n1)

    if [[ "$UPLOAD_HTTP_CODE" != "201" && "$UPLOAD_HTTP_CODE" != "200" ]]; then
      echo "  WARNING: Upload failed for ${SBOM_FILE_NAME}. HTTP Status: ${UPLOAD_HTTP_CODE}"
      SBOM_INDEX=$((SBOM_INDEX + 1))
      continue
    fi

    echo "  SBOM uploaded! HTTP Status: ${UPLOAD_HTTP_CODE}"

    # Trigger remote pipeline for this SBOM
    echo "  Triggering remote pipeline..."

    TRIGGER_RESPONSE=$(curl --silent --show-error --request POST \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      --header "Content-Type: application/json" \
      --data "{\"ref\": \"main\", \"variables\": [{\"key\": \"SBOM_SCAN_ID\", \"value\": \"${SCAN_ID}\"}, {\"key\": \"SBOM_FILE\", \"value\": \"${SBOM_FILE_NAME}\"}, {\"key\": \"SBOM_LANGUAGE\", \"value\": \"${SBOM_LANG}\"}]}" \
      "${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/pipeline")

    PIPELINE_ID=$(echo "$TRIGGER_RESPONSE" | jq -r '.id // empty' 2>/dev/null | tr -d '[:space:]')
    PIPELINE_IID=$(echo "$TRIGGER_RESPONSE" | jq -r '.iid // empty' 2>/dev/null | tr -d '[:space:]')

    if [[ -z "$PIPELINE_ID" ]]; then
      echo "  WARNING: Failed to trigger pipeline for ${SBOM_FILE_NAME}"
      SBOM_INDEX=$((SBOM_INDEX + 1))
      continue
    fi

    echo "  Pipeline triggered! ID: ${PIPELINE_ID}"
    PIPELINE_IDS+=("$PIPELINE_ID")
    REPORT_FILES+=("${ARTIFACTS_DIR}/vulnerability-findings-${SCAN_ID}.json:${SBOM_FILE_NAME}:${SBOM_LANG}")

    SBOM_INDEX=$((SBOM_INDEX + 1))
  done

  echo ""
  echo "Triggered ${#PIPELINE_IDS[@]} remote pipeline(s)"
  echo ""

  # Step 4: Wait for all pipelines to complete
  echo "Step 4/4: Waiting for all pipelines to complete..."
  echo ""

  for i in "${!PIPELINE_IDS[@]}"; do
    PIPELINE_ID="${PIPELINE_IDS[$i]}"
    REPORT_INFO="${REPORT_FILES[$i]}"
    REPORT_FILE=$(echo "$REPORT_INFO" | cut -d: -f1)
    SBOM_NAME=$(echo "$REPORT_INFO" | cut -d: -f2)
    SBOM_LANG=$(echo "$REPORT_INFO" | cut -d: -f3)

    echo "--- Waiting for pipeline ${PIPELINE_ID} (${SBOM_NAME}) ---"

    ELAPSED=0
    PIPELINE_STATUS="running"

    while [[ "$PIPELINE_STATUS" == "running" || "$PIPELINE_STATUS" == "pending" ]]; do
      if [[ $ELAPSED -ge $TIMEOUT ]]; then
        echo "  ERROR: Timeout waiting for pipeline ${PIPELINE_ID}"
        break
      fi

      sleep "$POLL_INTERVAL"
      ELAPSED=$((ELAPSED + POLL_INTERVAL))

      PIPELINE_STATUS=$(curl --silent --show-error \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/pipelines/${PIPELINE_ID}" | \
        grep -oP '"status"\s*:\s*"\K[^"]+' || echo "unknown")

      echo "  [${ELAPSED}s] Pipeline status: ${PIPELINE_STATUS}"
    done

    echo "  Pipeline ${PIPELINE_ID} completed: ${PIPELINE_STATUS}"

    # Download findings for this pipeline
    VULN_FINDINGS_URL="${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/vulnerability_findings?pipeline_id=${PIPELINE_ID}&report_type=dependency_scanning"

    curl --silent --show-error \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      --location \
      --output "${REPORT_FILE}" \
      "${VULN_FINDINGS_URL}"

    if [[ -f "${REPORT_FILE}" ]]; then
      echo "  Findings saved: ${REPORT_FILE}"
      SERVICE_REPORTS+=("${REPORT_FILE}:${SBOM_NAME}:${SBOM_LANG}")
    fi

    echo ""
  done

  # Merge all findings
  echo "=== Merging Vulnerability Findings ==="

  if [[ ${#SERVICE_REPORTS[@]} -eq 0 ]]; then
    echo "WARNING: No findings were collected" >&2
    return 1
  fi

  MERGED_REPORT="${ARTIFACTS_DIR}/vulnerability-findings-${BASE_SCAN_ID}-merged.json"

  if [[ ${#SERVICE_REPORTS[@]} -eq 1 ]]; then
    IFS=':' read -r report_path sbom_name sbom_lang <<< "${SERVICE_REPORTS[0]}"
    cp "$report_path" "$MERGED_REPORT"
    echo "Single SBOM scanned, report: $MERGED_REPORT"
  else
    echo "Merging ${#SERVICE_REPORTS[@]} findings reports..."

    MERGE_ARGS=()
    for report_info in "${SERVICE_REPORTS[@]}"; do
      IFS=':' read -r report_path sbom_name sbom_lang <<< "$report_info"
      if [[ -f "$report_path" ]]; then
        MERGE_ARGS+=("$report_path")
        echo "  - ${sbom_name} (${sbom_lang}): $report_path"
      fi
    done

    if [[ ${#MERGE_ARGS[@]} -gt 0 ]]; then
      # Merge all findings into single array
      jq -s 'add // []' "${MERGE_ARGS[@]}" > "$MERGED_REPORT"
      echo "Merged report: $MERGED_REPORT"
    fi
  fi

  echo ""
  echo "=== Multi-Service Dependency Scan Complete ==="
  echo "Total SBOMs processed: ${#SERVICE_REPORTS[@]}"
  echo "Merged findings: ${MERGED_REPORT}"

  return 0
}

# Main execution
echo "=== Remote Dependency Scan ==="
echo "GitLab: ${GITLAB_URL}"
echo ""

# Array to store all service report paths for merging
declare -a SERVICE_REPORTS=()

# Check if multi-service mode is enabled
if [[ -n "$SERVICES_JSON" && "$SERVICES_JSON" != "[]" ]]; then
  # For multi-service repos, run a single scan from project root
  # glci dependency-scanning will detect all languages and scan all services
  SERVICE_COUNT=$(echo "$SERVICES_JSON" | jq -r 'length' 2>/dev/null || echo "0")
  echo "Multi-service mode: Found ${SERVICE_COUNT} service(s)"
  echo "Running single scan from project root to detect all dependencies..."
  echo ""

  # Call the unified scan function
  scan_all_services

  echo ""
  echo "=== Multi-Service Dependency Scan Complete ==="
  echo "Total services covered: ${SERVICE_COUNT}"

else
  # Single-language mode (legacy behavior)
  if [[ -z "$LANGUAGE" ]]; then
    echo "ERROR: --language is required (or use --services for multi-service scan)" >&2
    echo "Supported: javascript, java, python, go, maven, gradle" >&2
    exit 1
  fi

  case "$LANGUAGE" in
    javascript|java|python|go|maven|gradle)
      ;;
    *)
      echo "ERROR: Unsupported language '$LANGUAGE'" >&2
      echo "Supported: javascript, java, python, go, maven, gradle" >&2
      exit 1
      ;;
  esac

  SCAN_ID="${BASE_SCAN_ID}"
  PIPELINE_FILE="${PROJECT_ROOT}/local-pipeline.yml"

  echo "Scan ID: ${SCAN_ID}"
  echo "Language: ${LANGUAGE}"
  echo "Source path: ${SOURCE_PATH}"
  echo ""

  cd "${PROJECT_ROOT}"

  # Copy standard pipeline template if local-pipeline.yml doesn't exist
  if [[ ! -f "$PIPELINE_FILE" ]]; then
    echo "Creating local-pipeline.yml from template..."
    cp "$SKILL_DIR/reference/std-pipeline.yml" "$PIPELINE_FILE"
  fi

  # Ensure GITLAB_FEATURES is set
  if ! grep -q "GITLAB_FEATURES" "$PIPELINE_FILE"; then
    if grep -q "^variables:" "$PIPELINE_FILE"; then
      sed -i '/^variables:/a\  GITLAB_FEATURES: "dependency_scanning"' "$PIPELINE_FILE"
    else
      sed -i '/^stages:/a\\nvariables:\n  GITLAB_FEATURES: "dependency_scanning"' "$PIPELINE_FILE"
    fi
  fi

  # Update language in pipeline
  sed -i "s|language: \${LANGUAGE}|language: $LANGUAGE|" "$PIPELINE_FILE"
  sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $LANGUAGE|" "$PIPELINE_FILE"

  echo "Step 1/4: Running local dependency scan..."
  set +e
  GLCI_OUTPUT=$(glci -f "$PIPELINE_FILE" run dependency-scanning --context "branch=main" --gitlab-url "$GITLAB_URL" --token "$GITLAB_TOKEN" 2>&1)
  set -e
  echo "$GLCI_OUTPUT"

  echo ""
  echo "Downloading SBOM artifacts..."
  set +e
  glci artifacts download dependency-scanning --output "${ARTIFACTS_DIR}" 2>&1
  set -e

  # Extract SBOM
  ZIP_FILE="${ARTIFACTS_DIR}/dependency-scanning.zip"
  if [[ -f "$ZIP_FILE" ]]; then
    unzip -o -q "$ZIP_FILE" -d "${ARTIFACTS_DIR}" >&2
    rm -f "$ZIP_FILE"
  fi

  # Find SBOM file
  for f in "${ARTIFACTS_DIR}"/gl-sbom-*.cdx.json; do
    if [[ -f "$f" ]]; then
      SBOM_FILE_PATH="$f"
      SBOM_FILE_NAME="$(basename "$f")"
      break
    fi
  done

  if [[ -z "$SBOM_FILE_PATH" ]]; then
    echo "ERROR: No SBOM file found" >&2
    exit 1
  fi

  echo "SBOM: ${SBOM_FILE_NAME}"
  echo ""

  # Upload SBOM
  echo "Step 2/4: Uploading SBOM..."
  UPLOAD_RESPONSE=$(curl --silent --show-error --write-out "\n%{http_code}" --request PUT \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --header "Content-Type: application/json" \
    --upload-file "${SBOM_FILE_PATH}" \
    "${GITLAB_URL}/api/v4/projects/${SBOM_PROJECT_ID}/packages/generic/local-sboms/${SCAN_ID}/${SBOM_FILE_NAME}")

  UPLOAD_HTTP_CODE=$(echo "$UPLOAD_RESPONSE" | tail -n1)
  if [[ "$UPLOAD_HTTP_CODE" != "201" && "$UPLOAD_HTTP_CODE" != "200" ]]; then
    echo "ERROR: Upload failed. HTTP Status: ${UPLOAD_HTTP_CODE}" >&2
    exit 1
  fi
  echo "SBOM uploaded successfully!"
  echo ""

  # Trigger pipeline
  echo "Step 3/4: Triggering remote pipeline..."
  TRIGGER_RESPONSE=$(curl --silent --show-error --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --header "Content-Type: application/json" \
    --data "{\"ref\": \"main\", \"variables\": [{\"key\": \"SBOM_SCAN_ID\", \"value\": \"${SCAN_ID}\"}, {\"key\": \"SBOM_FILE\", \"value\": \"${SBOM_FILE_NAME}\"}]}" \
    "${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/pipeline")

  PIPELINE_ID=$(echo "$TRIGGER_RESPONSE" | jq -r '.id // empty' 2>/dev/null | tr -d '[:space:]')
  if [[ -z "$PIPELINE_ID" ]]; then
    echo "ERROR: Failed to trigger pipeline" >&2
    exit 1
  fi
  echo "Pipeline triggered: ${PIPELINE_ID}"
  echo ""

  # Poll for completion
  echo "Step 4/4: Waiting for pipeline..."
  ELAPSED=0
  PIPELINE_STATUS="running"

  while [[ "$PIPELINE_STATUS" == "running" || "$PIPELINE_STATUS" == "pending" ]]; do
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
      echo "ERROR: Timeout (${TIMEOUT}s)" >&2
      exit 1
    fi
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
    PIPELINE_STATUS=$(curl --silent --show-error \
      --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
      "${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/pipelines/${PIPELINE_ID}" | \
      grep -oP '"status"\s*:\s*"\K[^"]+' || echo "unknown")
    echo "  [${ELAPSED}s] Status: ${PIPELINE_STATUS}"
  done

  echo ""
  echo "Pipeline: ${PIPELINE_STATUS}"
  echo ""

  # Download findings
  REPORT_FILE="vulnerability-findings-${SCAN_ID}.json"
  VULN_FINDINGS_URL="${GITLAB_URL}/api/v4/projects/${REMOTE_PROJECT_ID}/vulnerability_findings?pipeline_id=${PIPELINE_ID}&report_type=dependency_scanning"

  curl --silent --show-error \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --location \
    --output "${ARTIFACTS_DIR}/${REPORT_FILE}" \
    "${VULN_FINDINGS_URL}"

  if [[ -f "${ARTIFACTS_DIR}/${REPORT_FILE}" ]]; then
    echo "Results: ${ARTIFACTS_DIR}/${REPORT_FILE}"
  fi

  echo ""
  echo "=== Dependency Scan Complete ==="
fi

#!/bin/bash
#
# run-static-scan.sh — Run static security scans using glci with std-pipeline.yml
#
# IMPORTANT: This script is meant to be run FROM YOUR PROJECT REPO directory,
# not from the skill scripts directory. The script will:
#   - Copy the pipeline template to YOUR project root as local-pipeline.yml
#   - Create glci-artifacts/ directory in YOUR project root
#   - Run glci scans against YOUR project code
#
# Usage (automatic mode with args):
#   ./run-static-scan.sh --scan-type all --language javascript --source-path . --image myimage:tag
#   ./run-static-scan.sh --scan-type secret  # no additional args needed
#   ./run-static-scan.sh --scan-type sast --language python
#
# Usage (interactive mode, no args):
#   ./run-static-scan.sh  # will prompt for all inputs
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(pwd)"

PIPELINE_FILE="$PROJECT_ROOT/local-pipeline.yml"

GITLAB_URL="https://gitlab.<YOUR_GITLAB_INSTANCE>"
TOKEN="<YOUR_GITLAB_TOKEN>"

# Default values
SCAN_TYPE=""
LANGUAGE="javascript"
SOURCE_PATH="."
DOCKERFILE_PATH="Dockerfile"
JFROG_USER=""
JFROG_TOKEN=""
DOCKERFILES_DETECTED=""
MULTI_LANG=false

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --scan-type)
            SCAN_TYPE="$2"
            shift 2
            ;;
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --source-path)
            SOURCE_PATH="$2"
            shift 2
            ;;
        --jfrog-token)
            JFROG_TOKEN="$2"
            shift 2
            ;;
        --jfrog-user)
            JFROG_USER="$2"
            shift 2
            ;;
        --dockerfile-path)
            DOCKERFILE_PATH="$2"
            shift 2
            ;;
        --dockerfiles)
            # Comma-separated list of Dockerfiles to scan
            DOCKERFILES_INPUT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--scan-type TYPE] [--language LANG] [--source-path PATH] [--dockerfiles PATHS] [--jfrog-token TOKEN]"
            echo ""
            echo "Options:"
            echo "  --scan-type   all, secret, container, sast, or dependency (default: all)"
            echo "  --language    javascript, java, python, go, maven, gradle (default: javascript)"
            echo "  --source-path Path to source code (default: .)"
            echo "  --dockerfiles Comma-separated list of Dockerfile paths to scan"
            echo "  --dockerfile-path Path to single Dockerfile (deprecated, use --dockerfiles)"
            echo "  --jfrog-user  JFROG username for authentication"
            echo "  --jfrog-token JFROG auth token for pulling from private registries"
            echo ""
            echo "If no arguments provided, runs in interactive mode."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information."
            exit 1
            ;;
    esac
done

# Handle --dockerfiles input (overrides auto-detection)
if [[ -n "$DOCKERFILES_INPUT" ]]; then
    IFS=',' read -ra DOCKERFILES_ARRAY <<< "$DOCKERFILES_INPUT"
    DOCKERFILES_DETECTED=1
fi

# Interactive mode if no scan type specified
if [[ -z "$SCAN_TYPE" ]]; then
    echo "Select scan type:"
    echo "  1) All scans (SAST + Secret Detection + Image Scan + SCA)"
    echo "  2) Secret Detection only"
    echo "  3) Image Scan only"
    echo "  4) SAST only"
    echo "  5) SCA only"
    echo ""
    read -r SCAN_CHOICE

    case $SCAN_CHOICE in
        1) SCAN_TYPE="all" ;;
        2) SCAN_TYPE="secret" ;;
        3) SCAN_TYPE="container" ;;
        4) SCAN_TYPE="sast" ;;
        5) SCAN_TYPE="dependency" ;;
        *) echo "Invalid choice"; exit 1 ;;
    esac

    # Ask user for language and source path (required for SAST and dependency scanning)
    if [[ "$SCAN_TYPE" == "all" || "$SCAN_TYPE" == "sast" || "$SCAN_TYPE" == "dependency" ]]; then
        echo ""
        echo "Auto-detecting languages in the repository..."
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true

        # Parse detected languages
        mapfile -t LANGUAGES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.languages[]' 2>/dev/null)
        LANGUAGE_COUNT=${#LANGUAGES_ARRAY[@]}
        LANGUAGE="${LANGUAGES_ARRAY[0]}"  # Primary language for pipeline

        echo "Detected $LANGUAGE_COUNT language(s): ${LANGUAGES_ARRAY[*]}"
        echo "Will run SAST for all detected languages."
        MULTI_LANG=true

        echo "Source path (default: .):"
        read -r SOURCE_PATH
        SOURCE_PATH="${SOURCE_PATH:-.}"
    fi

    # Ask user for container scan details (required for Image Scan)
    if [[ "$SCAN_TYPE" == "all" || "$SCAN_TYPE" == "container" ]]; then
        # Run detect-inputs.sh to get Dockerfiles (non-interactive mode by default)
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true

        # Parse dockerfiles from JSON output using jq
        DOCKERFILE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.dockerfile_count // 0' 2>/dev/null) || DOCKERFILE_COUNT=0

        if [[ "$DOCKERFILE_COUNT" -eq 0 ]]; then
            echo ""
            echo "ERROR: No Dockerfile found in project ($PROJECT_ROOT)."
            echo "Container scanning requires a Dockerfile to build the image."
            echo "Please add a Dockerfile to your project or skip container scanning."
            exit 1
        fi

        # Parse dockerfiles array into a newline-separated list
        mapfile -t DOCKERFILES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.dockerfiles[]' 2>/dev/null)

        echo ""
        echo "Will scan ${#DOCKERFILES_ARRAY[@]} Dockerfile(s):"
        for df in "${DOCKERFILES_ARRAY[@]}"; do
            echo "  - $df"
        done
        echo ""

        # If JFROG_TOKEN not provided via argument, prompt for it
        if [[ -z "$JFROG_TOKEN" ]]; then
            echo "Does the image require JFROG authentication to pull from a private registry? (y/n):"
            read -r NEEDS_TOKEN
            if [[ "$NEEDS_TOKEN" == "y" || "$NEEDS_TOKEN" == "Y" ]]; then
                echo "Enter JFROG username:"
                read -r JFROG_USER
                echo "Enter JFROG_TOKEN:"
                read -r JFROG_TOKEN
            fi
        fi

        # Mark that we've already detected Dockerfiles (skip duplicate detection below)
        DOCKERFILES_DETECTED=1
    fi
fi

# Validate scan type
if [[ -z "$SCAN_TYPE" ]]; then
    echo "Error: Scan type not specified."
    exit 1
fi

# Map scan type aliases
case $SCAN_TYPE in
    all) SCAN_TYPE="all" ;;
    secret|secrets|secret-detection) SCAN_TYPE="secret" ;;
    container|image|container-scanning) SCAN_TYPE="container" ;;
    sast|sast-only) SCAN_TYPE="sast" ;;
    dependency|sca|dependency-scanning) SCAN_TYPE="dependency" ;;
    *) echo "Invalid scan type: $SCAN_TYPE. Must be: all, secret, container, sast, or dependency"; exit 1 ;;
esac

# Check for Dockerfile if container scan is requested (command-line mode)
# Skip if already detected during interactive mode
if [[ -z "$DOCKERFILES_DETECTED" ]] && [[ "$SCAN_TYPE" == "container" || "$SCAN_TYPE" == "all" ]]; then
    # If --dockerfile-path was explicitly provided, use it directly
    if [[ -n "$DOCKERFILE_PATH" && "$DOCKERFILE_PATH" != "Dockerfile" ]]; then
        echo ""
        echo "Using specified Dockerfile: $DOCKERFILE_PATH"
        DOCKERFILES_ARRAY=("$DOCKERFILE_PATH")
    else
        # Run detect-inputs.sh to get Dockerfiles (non-interactive mode)
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true

        # Parse dockerfiles from JSON output using jq
        DOCKERFILE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.dockerfile_count // 0' 2>/dev/null) || DOCKERFILE_COUNT=0

        if [[ "$DOCKERFILE_COUNT" -eq 0 ]]; then
            echo ""
            echo "ERROR: No Dockerfile found in project ($PROJECT_ROOT)."
            echo "Container scanning requires a Dockerfile to build the image."
            echo "Please add a Dockerfile to your project or skip container scanning."
            exit 1
        fi

        # Parse dockerfiles array into a newline-separated list
        mapfile -t DOCKERFILES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.dockerfiles[]' 2>/dev/null)

        echo ""
        echo "Will scan ${#DOCKERFILES_ARRAY[@]} Dockerfile(s):"
        for df in "${DOCKERFILES_ARRAY[@]}"; do
            echo "  - $df"
        done
    fi

    # If JFROG_TOKEN not provided via argument, prompt for it
    if [[ -z "$JFROG_TOKEN" ]]; then
        echo ""
        echo "Does the image require JFROG authentication to pull from a private registry? (y/n):"
        read -r NEEDS_TOKEN
        if [[ "$NEEDS_TOKEN" == "y" || "$NEEDS_TOKEN" == "Y" ]]; then
            echo "Enter JFROG username:"
            read -r JFROG_USER
            echo "Enter JFROG_TOKEN:"
            read -r JFROG_TOKEN
        fi
    fi
fi

# Copy template to project root
cp "$SKILL_DIR/reference/std-pipeline.yml" "$PIPELINE_FILE"

# Substitute variables in the pipeline file BEFORE running glci jobs
# Replace ${LANGUAGE}, ${SOURCE_PATH}, ${DOCKERFILE_PATH} with actual values
sed -i "s|\${LANGUAGE}|$LANGUAGE|g" "$PIPELINE_FILE"
sed -i "s|\${SOURCE_PATH}|$SOURCE_PATH|g" "$PIPELINE_FILE"
sed -i "s|\${DOCKERFILE_PATH}|$DOCKERFILE_PATH|g" "$PIPELINE_FILE"

# Also update the variables section at the top
sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $LANGUAGE|" "$PIPELINE_FILE"
sed -i "s|^  SOURCE_PATH: .*|  SOURCE_PATH: $SOURCE_PATH|" "$PIPELINE_FILE"
sed -i "s|^  DOCKERFILE_PATH: .*|  DOCKERFILE_PATH: $DOCKERFILE_PATH|" "$PIPELINE_FILE"

# Substitute JFROG credentials if provided
if [[ -n "$JFROG_TOKEN" ]]; then
    sed -i "s|JFROG_TOKEN: \${JFROG_TOKEN}|JFROG_TOKEN: $JFROG_TOKEN|" "$PIPELINE_FILE"
fi
if [[ -n "$JFROG_USER" ]]; then
    sed -i "s|JFROG_USER: \${JFROG_USER}|JFROG_USER: $JFROG_USER|" "$PIPELINE_FILE"
fi

echo ""
echo "Running: $SCAN_TYPE scan"
echo "Pipeline file: $PIPELINE_FILE"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
if bash "$SCRIPT_DIR/check-prereqs.sh" 2>&1; then
    echo ""
else
    echo ""
    echo "Note: Some prerequisites may be missing. Continuing anyway..."
    echo ""
fi

# Verify pipeline jobs are correctly detected (use same context as run)
echo "Verifying pipeline jobs..."
JOBS_OUTPUT=$(glci -f "$PIPELINE_FILE" jobs --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1) || true
echo "$JOBS_OUTPUT"
echo ""

# Create artifacts directory
ARTIFACTS_DIR="./glci-artifacts"
mkdir -p "$ARTIFACTS_DIR"

echo "========================================"
echo "Running Static Security Scans"
echo "========================================"
echo ""

# Run glci based on scan type and capture results
# Use --context "branch=main" to ensure secret-detection runs (not skipped as MR pipeline)

# Set GITLAB_FEATURES for dependency scanning support
# This must be exported before glci runs so it can pass to GitLab
export GITLAB_FEATURES="dependency_scanning"

case $SCAN_TYPE in
    all)
        # Detect all languages for multi-language SAST support (always use auto-detection)
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true
        LANGUAGE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.language_count // 1' 2>/dev/null) || LANGUAGE_COUNT=1
        mapfile -t LANGUAGES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.languages[]' 2>/dev/null)
        PRIMARY_LANGUAGE="${LANGUAGES_ARRAY[0]}"

        # Loop through each Dockerfile and scan
        if [[ ${#DOCKERFILES_ARRAY[@]} -gt 0 ]]; then
            CONTAINER_REPORTS=()
            for df in "${DOCKERFILES_ARRAY[@]}"; do
                DOCKERFILE_PATH="$df"
                # Create safe filename from Dockerfile path
                DF_SAFE_NAME=$(echo "$DOCKERFILE_PATH" | tr '/' '_' | tr '.' '_')

                # Update pipeline file with current Dockerfile path
                sed -i "s|^  DOCKERFILE_PATH: .*|  DOCKERFILE_PATH: $DOCKERFILE_PATH|" "$PIPELINE_FILE"
                sed -i "s|\${DOCKERFILE_PATH}|$DOCKERFILE_PATH|g" "$PIPELINE_FILE"

                echo ""
                echo "=== Building and scanning: $DOCKERFILE_PATH ==="

                # Run build_job first to build and push the image
                glci -f "$PIPELINE_FILE" run build_job --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                # Run full pipeline for all scanners (uses primary language for SAST)
                glci -f "$PIPELINE_FILE" run --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                # Download artifacts to temporary location for this Dockerfile
                TEMP_CONTAINER_DIR="$ARTIFACTS_DIR/container_${DF_SAFE_NAME}"
                mkdir -p "$TEMP_CONTAINER_DIR"
                glci artifacts download secret_detection --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true
                glci artifacts download container_scanning --output "$TEMP_CONTAINER_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                # Download SAST report for primary language
                SAST_JOB="fortify-sast-${PRIMARY_LANGUAGE}"
                glci artifacts download "$SAST_JOB" --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                # Store path to this container report for later merging
                if [[ -f "$TEMP_CONTAINER_DIR/gl-container-scanning-report.json" ]]; then
                    CONTAINER_REPORTS+=("$TEMP_CONTAINER_DIR/gl-container-scanning-report.json")
                    echo "  -> Saved container report: $TEMP_CONTAINER_DIR/gl-container-scanning-report.json"
                fi
            done

            # Merge all container reports into a single combined report
            if [[ ${#CONTAINER_REPORTS[@]} -gt 0 ]]; then
                echo ""
                echo "=== Merging ${#CONTAINER_REPORTS[@]} container scan reports ==="

                if [[ ${#CONTAINER_REPORTS[@]} -eq 1 ]]; then
                    cp "${CONTAINER_REPORTS[0]}" "$ARTIFACTS_DIR/gl-container-scanning-report.json"
                else
                    jq -s '
                        {
                            vulnerabilities: (map(.vulnerabilities // []) | add // []),
                            scan_metadata: {
                                merged_from: map(input_filename),
                                merged_at: now | todate,
                                total_dockerfiles: length
                            }
                        }
                    ' "${CONTAINER_REPORTS[@]}" > "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json"
                    cp "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json" "$ARTIFACTS_DIR/gl-container-scanning-report.json"
                    echo "  -> Merged report: $ARTIFACTS_DIR/gl-container-scanning-report-merged.json"
                fi
            fi

            # Handle multi-language SAST: run additional SAST scans for other languages
            if [[ "$LANGUAGE_COUNT" -gt 1 ]]; then
                echo ""
                echo "=== Running additional SAST scans for multi-language repo ==="
                SAST_REPORTS=()

                # First, save the primary language report
                if [[ -f "$ARTIFACTS_DIR/gl-sast-report.json" ]]; then
                    mkdir -p "$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}"
                    cp "$ARTIFACTS_DIR/gl-sast-report.json" "$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}/gl-sast-report.json"
                    SAST_REPORTS+=("$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}/gl-sast-report.json")
                fi

                # Parse languages array from JSON
                mapfile -t LANGUAGES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.languages[]' 2>/dev/null)

                # Run SAST for each additional language
                for lang in "${LANGUAGES_ARRAY[@]}"; do
                    if [[ "$lang" == "$PRIMARY_LANGUAGE" ]]; then
                        continue  # Already scanned primary language
                    fi

                    SAST_JOB="fortify-sast-${lang}"
                    echo ""
                    echo "=== Running SAST for additional language: $lang ==="

                    # Update pipeline file with current language
                    sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $lang|" "$PIPELINE_FILE"
                    sed -i "s|\${LANGUAGE}|$lang|g" "$PIPELINE_FILE"

                    # Run SAST scan for this language
                    glci -f "$PIPELINE_FILE" run "$SAST_JOB" --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                    # Download artifacts to temporary location for this language
                    TEMP_SAST_DIR="$ARTIFACTS_DIR/sast_${lang}"
                    mkdir -p "$TEMP_SAST_DIR"
                    glci artifacts download "$SAST_JOB" --output "$TEMP_SAST_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                    # Store path to this SAST report for later merging
                    if [[ -f "$TEMP_SAST_DIR/gl-sast-report.json" ]]; then
                        SAST_REPORTS+=("$TEMP_SAST_DIR/gl-sast-report.json")
                        echo "  -> Saved SAST report for $lang: $TEMP_SAST_DIR/gl-sast-report.json"
                    fi
                done

                # Merge all SAST reports into a single combined report
                if [[ ${#SAST_REPORTS[@]} -gt 1 ]]; then
                    echo ""
                    echo "=== Merging ${#SAST_REPORTS[@]} SAST reports ==="

                    jq -s '
                        {
                            vulnerabilities: (map(.vulnerabilities // []) | add // []),
                            scan_metadata: {
                                merged_from: map(input_filename),
                                merged_at: now | todate,
                                total_languages: length
                            }
                        }
                    ' "${SAST_REPORTS[@]}" > "$ARTIFACTS_DIR/gl-sast-report-merged.json"
                    cp "$ARTIFACTS_DIR/gl-sast-report-merged.json" "$ARTIFACTS_DIR/gl-sast-report.json"
                    echo "  -> Merged SAST report: $ARTIFACTS_DIR/gl-sast-report-merged.json"
                fi

                # Restore original language in pipeline file
                sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $PRIMARY_LANGUAGE|" "$PIPELINE_FILE"
                sed -i "s|\${LANGUAGE}|$PRIMARY_LANGUAGE|g" "$PIPELINE_FILE"
            fi

            # Run SBOM scan with remote upload and analysis (once after all container scans)
            # Use multi-service scanning if multiple services detected
            DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true
            SERVICE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.service_count // 0' 2>/dev/null) || SERVICE_COUNT=0

            if [[ "$SERVICE_COUNT" -gt 1 ]]; then
                echo ""
                echo "=== Running multi-service dependency scan ==="
                SERVICES_JSON=$(echo "$DETECT_OUTPUT" | jq -c '.services' 2>/dev/null)
                bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --services "$SERVICES_JSON" --project-root "$PROJECT_ROOT"
            else
                bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --language "$PRIMARY_LANGUAGE" --source-path "$SOURCE_PATH"
            fi
        else
            echo "Note: No Dockerfiles selected, skipping container build step"
            # Run non-container scans with primary language
            SAST_JOB="fortify-sast-${PRIMARY_LANGUAGE}"
            glci -f "$PIPELINE_FILE" run --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee "$ARTIFACTS_DIR/scan-output.log"
            glci artifacts download secret_detection --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true
            glci artifacts download "$SAST_JOB" --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

            # Handle multi-language SAST for non-Docker case
            if [[ "$LANGUAGE_COUNT" -gt 1 ]]; then
                echo ""
                echo "=== Running additional SAST scans for multi-language repo ==="
                SAST_REPORTS=()

                # First, save the primary language report
                if [[ -f "$ARTIFACTS_DIR/gl-sast-report.json" ]]; then
                    mkdir -p "$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}"
                    cp "$ARTIFACTS_DIR/gl-sast-report.json" "$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}/gl-sast-report.json"
                    SAST_REPORTS+=("$ARTIFACTS_DIR/sast_${PRIMARY_LANGUAGE}/gl-sast-report.json")
                fi

                # Run SAST for each additional language
                for lang in "${LANGUAGES_ARRAY[@]}"; do
                    if [[ "$lang" == "$PRIMARY_LANGUAGE" ]]; then
                        continue  # Already scanned primary language
                    fi

                    SAST_JOB="fortify-sast-${lang}"
                    echo ""
                    echo "=== Running SAST for additional language: $lang ==="

                    # Update pipeline file with current language
                    sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $lang|" "$PIPELINE_FILE"
                    sed -i "s|\${LANGUAGE}|$lang|g" "$PIPELINE_FILE"

                    # Run SAST scan for this language
                    glci -f "$PIPELINE_FILE" run "$SAST_JOB" --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                    # Download artifacts to temporary location for this language
                    TEMP_SAST_DIR="$ARTIFACTS_DIR/sast_${lang}"
                    mkdir -p "$TEMP_SAST_DIR"
                    glci artifacts download "$SAST_JOB" --output "$TEMP_SAST_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                    # Store path to this SAST report for later merging
                    if [[ -f "$TEMP_SAST_DIR/gl-sast-report.json" ]]; then
                        SAST_REPORTS+=("$TEMP_SAST_DIR/gl-sast-report.json")
                        echo "  -> Saved SAST report for $lang: $TEMP_SAST_DIR/gl-sast-report.json"
                    fi
                done

                # Merge all SAST reports into a single combined report
                if [[ ${#SAST_REPORTS[@]} -gt 1 ]]; then
                    echo ""
                    echo "=== Merging ${#SAST_REPORTS[@]} SAST reports ==="

                    jq -s '
                        {
                            vulnerabilities: (map(.vulnerabilities // []) | add // []),
                            scan_metadata: {
                                merged_from: map(input_filename),
                                merged_at: now | todate,
                                total_languages: length
                            }
                        }
                    ' "${SAST_REPORTS[@]}" > "$ARTIFACTS_DIR/gl-sast-report-merged.json"
                    cp "$ARTIFACTS_DIR/gl-sast-report-merged.json" "$ARTIFACTS_DIR/gl-sast-report.json"
                    echo "  -> Merged SAST report: $ARTIFACTS_DIR/gl-sast-report-merged.json"
                fi

                # Restore original language in pipeline file
                sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $PRIMARY_LANGUAGE|" "$PIPELINE_FILE"
                sed -i "s|\${LANGUAGE}|$PRIMARY_LANGUAGE|g" "$PIPELINE_FILE"
            fi

            # Run SBOM scan with remote upload and analysis
            # Use multi-service scanning if multiple services detected
            DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true
            SERVICE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.service_count // 0' 2>/dev/null) || SERVICE_COUNT=0

            if [[ "$SERVICE_COUNT" -gt 1 ]]; then
                echo ""
                echo "=== Running multi-service dependency scan ==="
                SERVICES_JSON=$(echo "$DETECT_OUTPUT" | jq -c '.services' 2>/dev/null)
                bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --services "$SERVICES_JSON" --project-root "$PROJECT_ROOT"
            else
                bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --language "$PRIMARY_LANGUAGE" --source-path "$SOURCE_PATH"
            fi
        fi
        ;;
    secret)
        glci -f "$PIPELINE_FILE" run secret_detection --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee "$ARTIFACTS_DIR/scan-output.log"
        glci artifacts download secret_detection --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true
        ;;
    container)
        # Loop through each Dockerfile and run container_scanning
        if [[ ${#DOCKERFILES_ARRAY[@]} -gt 0 ]]; then
            CONTAINER_REPORTS=()
            for df in "${DOCKERFILES_ARRAY[@]}"; do
                DOCKERFILE_PATH="$df"
                # Create safe filename from Dockerfile path
                DF_SAFE_NAME=$(echo "$DOCKERFILE_PATH" | tr '/' '_' | tr '.' '_')

                # Update pipeline file with current Dockerfile path
                sed -i "s|^  DOCKERFILE_PATH: .*|  DOCKERFILE_PATH: $DOCKERFILE_PATH|" "$PIPELINE_FILE"
                sed -i "s|\${DOCKERFILE_PATH}|$DOCKERFILE_PATH|g" "$PIPELINE_FILE"

                echo ""
                echo "=== Building and scanning: $DOCKERFILE_PATH ==="

                # Run container_scanning - build_job runs first via 'needs' directive
                glci -f "$PIPELINE_FILE" run container_scanning --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                # Download artifacts to temporary location for this Dockerfile
                TEMP_CONTAINER_DIR="$ARTIFACTS_DIR/container_${DF_SAFE_NAME}"
                mkdir -p "$TEMP_CONTAINER_DIR"
                glci artifacts download container_scanning --output "$TEMP_CONTAINER_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                # Store path to this report for later merging
                if [[ -f "$TEMP_CONTAINER_DIR/gl-container-scanning-report.json" ]]; then
                    CONTAINER_REPORTS+=("$TEMP_CONTAINER_DIR/gl-container-scanning-report.json")
                    echo "  -> Saved report: $TEMP_CONTAINER_DIR/gl-container-scanning-report.json"
                fi
            done

            # Merge all container reports into a single combined report
            if [[ ${#CONTAINER_REPORTS[@]} -gt 0 ]]; then
                echo ""
                echo "=== Merging ${#CONTAINER_REPORTS[@]} container scan reports ==="

                # Use jq to merge all vulnerabilities arrays into one combined report
                if [[ ${#CONTAINER_REPORTS[@]} -eq 1 ]]; then
                    # Single report - just copy it
                    cp "${CONTAINER_REPORTS[0]}" "$ARTIFACTS_DIR/gl-container-scanning-report.json"
                else
                    # Multiple reports - merge vulnerabilities from all
                    jq -s '
                        {
                            vulnerabilities: (map(.vulnerabilities // []) | add // []),
                            scan_metadata: {
                                merged_from: map(input_filename),
                                merged_at: now | todate,
                                total_dockerfiles: length
                            }
                        }
                    ' "${CONTAINER_REPORTS[@]}" > "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json"

                    # Also create the standard name for backward compatibility
                    cp "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json" "$ARTIFACTS_DIR/gl-container-scanning-report.json"

                    echo "  -> Merged report: $ARTIFACTS_DIR/gl-container-scanning-report-merged.json"
                fi
            fi
        else
            echo "Note: No Dockerfiles selected, skipping container scanning"
        fi
        ;;
    sast)
        # Auto-detect languages and run SAST for each detected language
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true
        mapfile -t LANGUAGES_ARRAY < <(echo "$DETECT_OUTPUT" | jq -r '.languages[]' 2>/dev/null)
        LANGUAGE_COUNT=${#LANGUAGES_ARRAY[@]}
        LANGUAGE="${LANGUAGES_ARRAY[0]}"  # Primary language for pipeline file

        echo ""
        echo "=== Detected ${#LANGUAGES_ARRAY[@]} language(s): ${LANGUAGES_ARRAY[*]} ==="

        if [[ "$LANGUAGE_COUNT" -gt 1 ]]; then
            echo "=== Running SAST separately for each language ==="
            SAST_REPORTS=()

            # Run SAST for each language
            for lang in "${LANGUAGES_ARRAY[@]}"; do
                SAST_JOB="fortify-sast-${lang}"
                echo ""
                echo "=== Running SAST for language: $lang ==="

                # Update pipeline file with current language
                sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $lang|" "$PIPELINE_FILE"
                sed -i "s|\${LANGUAGE}|$lang|g" "$PIPELINE_FILE"

                # Run SAST scan for this language
                glci -f "$PIPELINE_FILE" run "$SAST_JOB" --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee -a "$ARTIFACTS_DIR/scan-output.log"

                # Download artifacts to temporary location for this language
                TEMP_SAST_DIR="$ARTIFACTS_DIR/sast_${lang}"
                mkdir -p "$TEMP_SAST_DIR"
                glci artifacts download "$SAST_JOB" --output "$TEMP_SAST_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true

                # Store path to this SAST report for later merging
                if [[ -f "$TEMP_SAST_DIR/gl-sast-report.json" ]]; then
                    SAST_REPORTS+=("$TEMP_SAST_DIR/gl-sast-report.json")
                    echo "  -> Saved SAST report for $lang: $TEMP_SAST_DIR/gl-sast-report.json"
                fi
            done

            # Merge all SAST reports into a single combined report
            if [[ ${#SAST_REPORTS[@]} -gt 0 ]]; then
                echo ""
                echo "=== Merging ${#SAST_REPORTS[@]} SAST reports ==="

                if [[ ${#SAST_REPORTS[@]} -eq 1 ]]; then
                    cp "${SAST_REPORTS[0]}" "$ARTIFACTS_DIR/gl-sast-report.json"
                else
                    jq -s '
                        {
                            vulnerabilities: (map(.vulnerabilities // []) | add // []),
                            scan_metadata: {
                                merged_from: map(input_filename),
                                merged_at: now | todate,
                                total_languages: length
                            }
                        }
                    ' "${SAST_REPORTS[@]}" > "$ARTIFACTS_DIR/gl-sast-report-merged.json"
                    cp "$ARTIFACTS_DIR/gl-sast-report-merged.json" "$ARTIFACTS_DIR/gl-sast-report.json"
                    echo "  -> Merged SAST report: $ARTIFACTS_DIR/gl-sast-report-merged.json"
                fi
            fi

            # Restore original language in pipeline file
            sed -i "s|^  LANGUAGE: .*|  LANGUAGE: $LANGUAGE|" "$PIPELINE_FILE"
            sed -i "s|\${LANGUAGE}|$LANGUAGE|g" "$PIPELINE_FILE"
        else
            # Single language - run SAST normally
            SAST_JOB="fortify-sast-${LANGUAGE}"
            glci -f "$PIPELINE_FILE" run "$SAST_JOB" --gitlab-url "$GITLAB_URL" --token "$TOKEN" --context "branch=main" 2>&1 | tee "$ARTIFACTS_DIR/scan-output.log"
            glci artifacts download "$SAST_JOB" --output "$ARTIFACTS_DIR/" --gitlab-url "$GITLAB_URL" --token "$TOKEN" 2>/dev/null || true
        fi
        ;;
    dependency)
        # Auto-detect all services and languages, then scan each one
        echo "=== Auto-detecting services and languages for dependency scanning ==="
        DETECT_OUTPUT=$(bash "$SCRIPT_DIR/detect-inputs.sh" "$PROJECT_ROOT") || true

        SERVICE_COUNT=$(echo "$DETECT_OUTPUT" | jq -r '.service_count // 0' 2>/dev/null) || SERVICE_COUNT=0

        if [[ "$SERVICE_COUNT" -eq 0 ]]; then
            echo "No services detected, falling back to single-language scan"
            bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --language "$LANGUAGE" --source-path "$SOURCE_PATH"
        elif [[ "$SERVICE_COUNT" -eq 1 ]]; then
            # Single service - extract and scan
            SERVICE_LANG=$(echo "$DETECT_OUTPUT" | jq -r '.services[0].language' 2>/dev/null)
            SERVICE_PATH=$(echo "$DETECT_OUTPUT" | jq -r '.services[0].path' 2>/dev/null)
            echo "Detected single service: ${SERVICE_PATH} (${SERVICE_LANG})"
            bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --language "$SERVICE_LANG" --source-path "$SERVICE_PATH"
        else
            # Multiple services - scan all of them
            echo "Detected ${SERVICE_COUNT} services, scanning all..."
            SERVICES_JSON=$(echo "$DETECT_OUTPUT" | jq -c '.services' 2>/dev/null)
            bash "$SCRIPT_DIR/scan-and-upload-sbom.sh" --services "$SERVICES_JSON" --project-root "$PROJECT_ROOT"
        fi
        ;;
esac

# Aggregate findings into a summary table
echo ""
echo "========================================"
echo "           SCAN SUMMARY"
echo "========================================"
echo ""

# Initialize counters
SAST_FINDINGS=0
SECRET_FINDINGS=0
CONTAINER_FINDINGS=0
SCA_FINDINGS=0

# Extract and count findings from artifact reports
echo "Extracting and analyzing scan reports..."

# Function to count vulnerabilities from JSON report
count_vulnerabilities() {
    local json_file="$1"
    if [[ -f "$json_file" ]]; then
        # Count items in vulnerabilities array using jq
        jq '.vulnerabilities | length' "$json_file" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Extract and count Secret Detection findings
if [[ -f "$ARTIFACTS_DIR/secret_detection.zip" ]]; then
    echo "  - Processing Secret Detection report..."
    unzip -o -q "$ARTIFACTS_DIR/secret_detection.zip" -d "$ARTIFACTS_DIR/" 2>/dev/null || true
    if [[ -f "$ARTIFACTS_DIR/gl-secret-detection-report.json" ]]; then
        SECRET_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-secret-detection-report.json")
    fi
fi

# Extract and count Container Scanning findings
# First check for merged report (multi-Dockerfile scan)
if [[ -f "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json" ]]; then
    echo "  - Processing merged Container Scanning report..."
    CONTAINER_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json")
elif [[ -f "$ARTIFACTS_DIR/gl-container-scanning-report.json" ]]; then
    echo "  - Processing Container Scanning report..."
    CONTAINER_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-container-scanning-report.json")
elif [[ -f "$ARTIFACTS_DIR/container_scanning.zip" ]]; then
    echo "  - Processing Container Scanning report..."
    unzip -o -q "$ARTIFACTS_DIR/container_scanning.zip" -d "$ARTIFACTS_DIR/" 2>/dev/null || true
    if [[ -f "$ARTIFACTS_DIR/gl-container-scanning-report.json" ]]; then
        CONTAINER_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-container-scanning-report.json")
    fi
else
    # Check for per-Dockerfile reports and merge on the fly for counting
    echo "  - Looking for per-Dockerfile container reports..."
    CONTAINER_FINDINGS=0
    for docker_dir in "$ARTIFACTS_DIR"/container_*/; do
        if [[ -d "$docker_dir" ]]; then
            if [[ -f "$docker_dir/gl-container-scanning-report.json" ]]; then
                COUNT=$(count_vulnerabilities "$docker_dir/gl-container-scanning-report.json")
                CONTAINER_FINDINGS=$((CONTAINER_FINDINGS + COUNT))
                echo "    - $(basename "$docker_dir"): $COUNT vulnerabilities"
            elif [[ -f "$docker_dir/container_scanning.zip" ]]; then
                unzip -o -q "$docker_dir/container_scanning.zip" -d "$docker_dir/" 2>/dev/null || true
                if [[ -f "$docker_dir/gl-container-scanning-report.json" ]]; then
                    COUNT=$(count_vulnerabilities "$docker_dir/gl-container-scanning-report.json")
                    CONTAINER_FINDINGS=$((CONTAINER_FINDINGS + COUNT))
                    echo "    - $(basename "$docker_dir"): $COUNT vulnerabilities"
                fi
            fi
        fi
    done
    # Create merged report if we found per-Dockerfile reports
    if [[ $CONTAINER_FINDINGS -gt 0 ]]; then
        echo "  - Creating merged report from per-Dockerfile scans..."
        MERGE_FILES=()
        for docker_dir in "$ARTIFACTS_DIR"/container_*/; do
            if [[ -f "$docker_dir/gl-container-scanning-report.json" ]]; then
                MERGE_FILES+=("$docker_dir/gl-container-scanning-report.json")
            fi
        done
        if [[ ${#MERGE_FILES[@]} -gt 0 ]]; then
            jq -s '
                {
                    vulnerabilities: (map(.vulnerabilities // []) | add // []),
                    scan_metadata: {
                        merged_from: map(input_filename),
                        merged_at: now | todate,
                        total_dockerfiles: length
                    }
                }
            ' "${MERGE_FILES[@]}" > "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json"
            cp "$ARTIFACTS_DIR/gl-container-scanning-report-merged.json" "$ARTIFACTS_DIR/gl-container-scanning-report.json"
        fi
    fi
fi

# Extract and count SAST findings
# First check for merged multi-language report
if [[ -f "$ARTIFACTS_DIR/gl-sast-report-merged.json" ]]; then
    echo "  - Processing merged multi-language SAST report..."
    SAST_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-sast-report-merged.json")
elif [[ -f "$ARTIFACTS_DIR/gl-sast-report.json" ]]; then
    echo "  - Processing SAST report..."
    SAST_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-sast-report.json")
else
    # Check for per-language reports and sum them up
    echo "  - Looking for per-language SAST reports..."
    SAST_FINDINGS=0
    for sast_dir in "$ARTIFACTS_DIR"/sast_*/; do
        if [[ -d "$sast_dir" ]]; then
            if [[ -f "$sast_dir/gl-sast-report.json" ]]; then
                COUNT=$(count_vulnerabilities "$sast_dir/gl-sast-report.json")
                SAST_FINDINGS=$((SAST_FINDINGS + COUNT))
                echo "    - $(basename "$sast_dir"): $COUNT vulnerabilities"
            elif [[ -f "$sast_dir/fortify-sast-*.zip" ]]; then
                unzip -o -q "$sast_dir/fortify-sast-"*.zip -d "$sast_dir/" 2>/dev/null || true
                if [[ -f "$sast_dir/gl-sast-report.json" ]]; then
                    COUNT=$(count_vulnerabilities "$sast_dir/gl-sast-report.json")
                    SAST_FINDINGS=$((SAST_FINDINGS + COUNT))
                    echo "    - $(basename "$sast_dir"): $COUNT vulnerabilities"
                fi
            fi
        fi
    done

    # Create merged report if we found per-language reports
    if [[ $SAST_FINDINGS -gt 0 ]]; then
        echo "  - Creating merged report from per-language scans..."
        MERGE_FILES=()
        for sast_dir in "$ARTIFACTS_DIR"/sast_*/; do
            if [[ -f "$sast_dir/gl-sast-report.json" ]]; then
                MERGE_FILES+=("$sast_dir/gl-sast-report.json")
            fi
        done
        if [[ ${#MERGE_FILES[@]} -gt 0 ]]; then
            jq -s '
                {
                    vulnerabilities: (map(.vulnerabilities // []) | add // []),
                    scan_metadata: {
                        merged_from: map(input_filename),
                        merged_at: now | todate,
                        total_languages: length
                    }
                }
            ' "${MERGE_FILES[@]}" > "$ARTIFACTS_DIR/gl-sast-report-merged.json"
            cp "$ARTIFACTS_DIR/gl-sast-report-merged.json" "$ARTIFACTS_DIR/gl-sast-report.json"
        fi
    fi
fi

# Extract and count SCA/Dependency Scanning findings
# Check for merged multi-service findings first, then individual scans
SCA_FINDINGS=0

# First check for merged multi-service report
MERGED_FILE=$(ls "$ARTIFACTS_DIR"/vulnerability-findings-*-merged.json 2>/dev/null | head -1)
if [[ -n "$MERGED_FILE" && -f "$MERGED_FILE" ]]; then
  echo "  - Processing merged multi-service dependency scan report..."
  SCA_FINDINGS=$(jq 'length' "$MERGED_FILE" 2>/dev/null || echo "0")
else
  # Check for individual scan findings (per-SBOM reports)
  echo "  - Processing individual dependency scan reports..."
  for f in "$ARTIFACTS_DIR"/vulnerability-findings-scan-*.json; do
    if [[ -f "$f" ]]; then
      # Skip merged files, only count individual SBOM reports
      if [[ "$f" != *"-merged.json" ]]; then
        COUNT=$(jq 'length' "$f" 2>/dev/null || echo "0")
        SCA_FINDINGS=$((SCA_FINDINGS + COUNT))
        echo "    - $(basename "$f"): $COUNT vulnerabilities"
      fi
    fi
  done
fi

# Fallback to old dependency_scanning.zip format
if [[ "$SCA_FINDINGS" -eq 0 ]] && [[ -f "$ARTIFACTS_DIR/dependency_scanning.zip" ]]; then
  unzip -o -q "$ARTIFACTS_DIR/dependency_scanning.zip" -d "$ARTIFACTS_DIR/" 2>/dev/null || true
  if [[ -f "$ARTIFACTS_DIR/gl-dependency-scanning-report.json" ]]; then
    SCA_FINDINGS=$(count_vulnerabilities "$ARTIFACTS_DIR/gl-dependency-scanning-report.json")
  fi
fi

TOTAL_FINDINGS=$((SAST_FINDINGS + SECRET_FINDINGS + CONTAINER_FINDINGS + SCA_FINDINGS))

# Print summary table
echo "+----------------------+------------+"
echo "| Scanner            | Findings   |"
echo "+----------------------+------------+"
printf "| %-20s | %-10s |\n" "SAST (Fortify)" "$SAST_FINDINGS"
printf "| %-20s | %-10s |\n" "Secret Detection" "$SECRET_FINDINGS"
printf "| %-20s | %-10s |\n" "Image Scan" "$CONTAINER_FINDINGS"
printf "| %-20s | %-10s |\n" "SCA (Dependency)" "$SCA_FINDINGS"
echo "+----------------------+------------+"
printf "| %-20s | %-10s |\n" "TOTAL" "$TOTAL_FINDINGS"
echo "+----------------------+------------+"
echo ""

if [[ $TOTAL_FINDINGS -gt 0 ]]; then
    echo "Review detailed findings in the extracted reports:"
    [[ $SAST_FINDINGS -gt 0 ]] && echo "  - SAST: $ARTIFACTS_DIR/gl-sast-report.json (and fortify.html)"
    [[ $SECRET_FINDINGS -gt 0 ]] && echo "  - Secret Detection: $ARTIFACTS_DIR/gl-secret-detection-report.json"
    [[ $CONTAINER_FINDINGS -gt 0 ]] && echo "  - Container Scanning: $ARTIFACTS_DIR/gl-container-scanning-report.json"
    if [[ $SCA_FINDINGS -gt 0 ]]; then
        # Check if this was a multi-service scan
        if [[ -f "$ARTIFACTS_DIR/vulnerability-findings-*-merged.json" ]]; then
            MERGED_FILE=$(ls "$ARTIFACTS_DIR"/vulnerability-findings-*-merged.json 2>/dev/null | head -1)
            echo "  - SCA/Dependency (multi-service merged): $MERGED_FILE"
            # Show per-service breakdown
            echo "    Per-service reports:"
            for svc_dir in "$ARTIFACTS_DIR"/svc-*/; do
                if [[ -d "$svc_dir" ]]; then
                    for vf in "$svc_dir"/vulnerability-findings-*.json; do
                        if [[ -f "$vf" ]]; then
                            COUNT=$(jq 'length' "$vf" 2>/dev/null || echo "0")
                            echo "      - $(basename "$svc_dir"): $COUNT vulnerabilities"
                        fi
                    done
                fi
            done
        else
            echo "  - SCA/Dependency: $ARTIFACTS_DIR/vulnerability-findings-*.json or gl-dependency-scanning-report.json"
        fi
    fi
else
    echo "No findings detected. Great job!"
fi

echo ""
echo "Static AppSec Scan completed."

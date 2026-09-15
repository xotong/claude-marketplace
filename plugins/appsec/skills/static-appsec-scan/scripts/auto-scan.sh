#!/bin/bash
#
# auto-scan.sh — Fully automatic security scan with auto-detected inputs
#
# Usage:
#   ./auto-scan.sh [--scan-type all|secret|container|sast|dependency] [--confirm]
#
# Options:
#   --scan-type   Override detected scan type
#   --confirm     Skip user confirmation and proceed with detected values
#   -h, --help    Show this help message
#
# This script:
#   1. Detects language, container image, and source path from repo
#   2. Optionally confirms with user (unless --confirm)
#   3. Runs the scan automatically
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIRM=false
OVERRIDE_SCAN_TYPE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --scan-type)
            OVERRIDE_SCAN_TYPE="$2"
            shift 2
            ;;
        --confirm)
            CONFIRM=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--scan-type TYPE] [--confirm]"
            echo ""
            echo "Automatically detects repository inputs and runs security scan."
            echo ""
            echo "Options:"
            echo "  --scan-type   Override detected scan type (all|secret|container|sast|dependency)"
            echo "  --confirm     Skip user confirmation, proceed with detected values"
            echo "  -h, --help    Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage."
            exit 1
            ;;
    esac
done

echo "🔍 Detecting repository inputs..."
echo ""

# Run detection script and parse JSON output
DETECTION=$("$SCRIPT_DIR/detect-inputs.sh")

LANGUAGE=$(echo "$DETECTION" | jq -r '.language')
SOURCE_PATH=$(echo "$DETECTION" | jq -r '.source_path')
IMAGE=$(echo "$DETECTION" | jq -r '.image')
DETECTED_SCAN_TYPE=$(echo "$DETECTION" | jq -r '.scan_type_recommendation')

# Apply override if provided
SCAN_TYPE="${OVERRIDE_SCAN_TYPE:-$DETECTED_SCAN_TYPE}"

echo "Detected values:"
echo "  Language:      $LANGUAGE"
echo "  Source path:   $SOURCE_PATH"
echo "  Image:         $IMAGE"
echo "  Scan type:     $SCAN_TYPE"
echo ""

# Confirm with user unless --confirm flag is set
if [[ "$CONFIRM" != true ]]; then
    echo "Proceed with these settings? (yes/no)"
    read -r CONFIRMATION
    if [[ "$CONFIRMATION" != "yes" && "$CONFIRMATION" != "y" ]]; then
        echo "Aborting. You can run with --scan-type, --language, --image flags to override."
        exit 0
    fi
fi

echo ""
echo "🚀 Running security scan..."
echo ""

# Run the scan with detected values
"$SCRIPT_DIR/run-static-scan.sh" \
    --scan-type "$SCAN_TYPE" \
    --language "$LANGUAGE" \
    --source-path "$SOURCE_PATH" \
    --image "$IMAGE"

echo ""
echo "✅ Scan complete!"

#!/bin/bash
#
# check-prereqs.sh — Check prerequisites for glci and offer to install missing items
#
# Usage:
#   ./check-prereqs.sh [--config <path>]
#
# Checks for:
#   - jq (JSON parser)
#   - glci binary
#   - Required Docker images
#
# Will prompt to install glci if missing.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$SKILL_DIR/config/scanner-preferences.yaml"

# Default values
GLCI_DOWNLOAD_URL="https://artifactory.<YOUR_DOMAIN>/artifactory/software/glci/glci"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--config <path>]

Check prerequisites for static-appsec-scan and offer to install missing items.

Options:
  --config      Path to scanner-preferences.yaml (default: config/scanner-preferences.yaml)
  -h, --help    Show this help message

Checks for:
  - jq (JSON parser)
  - glci binary in PATH or at GLCI_INSTALL_PATH
  - Docker images: alpine:latest, gitlab/gitlab-runner, gitlab-runner-helper

If glci is missing, you will be prompted to download it.
EOF
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_ok() { echo -e "${GREEN}✓${NC} $1"; }
echo_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
echo_err() { echo -e "${RED}✗${NC} $1"; }

# Track missing prerequisites
MISSING_GLCI=false
MISSING_JQ=false
MISSING_IMAGES=()

echo "=== Checking Prerequisites ==="
echo ""

# Check for jq (required for JSON parsing in run-static-scan.sh)
if command -v jq &>/dev/null; then
  JQ_PATH="$(which jq)"
  echo_ok "jq found: $JQ_PATH"
else
  echo_err "jq not found"
  echo "  Install: sudo apt-get install jq  # Debian/Ubuntu"
  echo "         or: sudo yum install jq   # RHEL/CentOS"
  echo "         or: brew install jq       # macOS"
  MISSING_JQ=true
fi

# Load preferences if config exists
if [[ -f "$CONFIG_FILE" ]]; then
  echo "Loading configuration from: $CONFIG_FILE"

  # Use python3 to read YAML (yq not required)
  if command -v python3 &>/dev/null; then
    GLCI_INSTALL_PATH="$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('settings', {}).get('prerequisites', {}).get('glci_install_path', '~/.glci/bin/glci'))
")"
    GLCI_DOWNLOAD_URL="$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('settings', {}).get('prerequisites', {}).get('glci_download_url', ''))
")"
  else
    echo_warn "python3 not found — using defaults"
    GLCI_INSTALL_PATH="~/.glci/bin/glci"
  fi
else
  echo_warn "Config file not found: $CONFIG_FILE"
  GLCI_INSTALL_PATH="~/.glci/bin/glci"
fi

# Expand tilde
GLCI_INSTALL_PATH="${GLCI_INSTALL_PATH/#\~/$HOME}"

# Check for glci
if command -v glci &>/dev/null; then
  GLCI_PATH="$(which glci)"
  echo_ok "glci found in PATH: $GLCI_PATH"
  glci --version 2>/dev/null || true
else
  echo_warn "glci not found in PATH"
  MISSING_GLCI=true

  # Check install path
  if [[ -f "$GLCI_INSTALL_PATH" ]]; then
    echo_ok "glci found at install path: $GLCI_INSTALL_PATH"
    echo "  Add to PATH: export PATH=\"\$PATH:$(dirname "$GLCI_INSTALL_PATH")\""
    MISSING_GLCI=false
  else
    echo_err "glci not found at install path: $GLCI_INSTALL_PATH"

    # Prompt user to download glci
    echo ""
    read -p "Would you like to download glci? [y/N] " -r INSTALL_CHOICE
    echo ""
    if [[ "$INSTALL_CHOICE" =~ ^[Yy]$ ]]; then
      echo "Downloading glci from: $GLCI_DOWNLOAD_URL"
      mkdir -p "$(dirname "$GLCI_INSTALL_PATH")"

      # Detect OS and arch
      OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
      ARCH="$(uname -m)"
      case "$ARCH" in
        x86_64) ARCH="amd64" ;;
        aarch64|arm64) ARCH="arm64" ;;
      esac

      # Substitute placeholders
      DOWNLOAD_URL="${GLCI_DOWNLOAD_URL//\{os\}/$OS}"
      DOWNLOAD_URL="${DOWNLOAD_URL//\{arch\}/$ARCH}"

      if curl -fsSL -o "$GLCI_INSTALL_PATH" "$DOWNLOAD_URL"; then
        chmod +x "$GLCI_INSTALL_PATH"
        echo_ok "Downloaded glci to: $GLCI_INSTALL_PATH"
        echo "  Add to PATH: export PATH=\"\$PATH:$(dirname "$GLCI_INSTALL_PATH")\""
        MISSING_GLCI=false
      else
        echo_err "Failed to download glci"
        echo "  You can also download manually from: $GLCI_DOWNLOAD_URL"
      fi
    else
      echo "  Skipping glci download."
      echo "  Manual install: curl -fsSL -o ~/.glci/bin/glci $GLCI_DOWNLOAD_URL && chmod +x ~/.glci/bin/glci"
    fi
  fi
fi

echo ""
echo "--- Docker Images ---"

# Required images: LOCAL_TAG|SOURCE_URL (use same if SOURCE_URL is empty)
declare -A REQUIRED_IMAGES=(
  ["alpine:latest"]="docker-cdc.artifactory.<YOUR_DOMAIN>/glci-images/alpine:latest"
  ["gitlab/gitlab-runner:latest"]="docker-cdc.artifactory.<YOUR_DOMAIN>/glci-images/gitlab-runner:latest"
  ["registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v19.2.1"]="docker-cdc.artifactory.<YOUR_DOMAIN>/glci-images/gitlab-runner-helper:x86_64-v19.2.1"
  ["registry.gitlab.com/gitlab-org/ci-cd/runner-tools/glci:latest"]="docker-cdc.artifactory.<YOUR_DOMAIN>/glci-images/glci:latest"
)

# Check each image (check by local tag)
for LOCAL_TAG in "${!REQUIRED_IMAGES[@]}"; do
  SOURCE_URL="${REQUIRED_IMAGES[$LOCAL_TAG]}"
  # If no source URL specified, use local tag as source
  [[ -z "$SOURCE_URL" ]] && SOURCE_URL="$LOCAL_TAG"

  # Check if image exists locally
  if docker image inspect "$LOCAL_TAG" &>/dev/null; then
    echo_ok "$LOCAL_TAG — found"
  else
    echo_warn "$LOCAL_TAG — not found"
    MISSING_IMAGES+=("$LOCAL_TAG|$SOURCE_URL")
  fi
done

# Prompt to pull missing images
if [[ ${#MISSING_IMAGES[@]} -gt 0 ]]; then
  echo ""
  read -p "Would you like to pull the missing Docker images? [y/N] " -r PULL_CHOICE
  echo ""
  if [[ "$PULL_CHOICE" =~ ^[Yy]$ ]]; then
    for ENTRY in "${MISSING_IMAGES[@]}"; do
      LOCAL_TAG="${ENTRY%%|*}"
      SOURCE_URL="${ENTRY#*|}"
      echo "Pulling $SOURCE_URL as $LOCAL_TAG..."
      if docker pull "$SOURCE_URL" 2>/dev/null; then
        # Tag it with the expected local name if different
        if [[ "$SOURCE_URL" != "$LOCAL_TAG" ]]; then
          docker tag "$SOURCE_URL" "$LOCAL_TAG" 2>/dev/null || true
        fi
        echo_ok "$LOCAL_TAG — pulled successfully"
        # Remove from missing list
        MISSING_IMAGES=("${MISSING_IMAGES[@]/$ENTRY}")
      else
        echo_err "$LOCAL_TAG — pull failed"
      fi
    done
  else
    echo "Skipping Docker image pull."
    echo "Pull manually:"
    for ENTRY in "${MISSING_IMAGES[@]}"; do
      LOCAL_TAG="${ENTRY%%|*}"
      SOURCE_URL="${ENTRY#*|}"
      if [[ "$SOURCE_URL" != "$LOCAL_TAG" ]]; then
        echo "  docker pull $SOURCE_URL && docker tag $SOURCE_URL $LOCAL_TAG"
      else
        echo "  docker pull $LOCAL_TAG"
      fi
    done
  fi
fi

echo ""
echo "=== Summary ==="

if [[ "$MISSING_GLCI" == "false" && "$MISSING_JQ" == "false" && ${#MISSING_IMAGES[@]} -eq 0 ]]; then
  echo_ok "All prerequisites satisfied!"
  exit 0
else
  echo_warn "Missing prerequisites:"
  [[ "$MISSING_GLCI" == "true" ]] && echo "  - glci binary"
  [[ "$MISSING_JQ" == "true" ]] && echo "  - jq (JSON parser)"
  for IMAGE in "${MISSING_IMAGES[@]}"; do
    echo "  - $IMAGE"
  done
  echo ""

  # jq - just show install instructions
  if [[ "$MISSING_JQ" == "true" ]]; then
    echo "  # Install jq:"
    echo "  sudo apt-get install jq  # Ubuntu"
    echo "  sudo yum install jq      # RHEL"
    echo ""
  fi

  exit 1
fi

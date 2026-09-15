#!/bin/bash
#
# check-package-availability.sh — Check if a package is available in company repositories
#
# Usage:
#   ./check-package-availability.sh --package <name> --language <lang> [--version <version>]
#
# This script checks if a package is available in:
#   - npm-airlock: https://artifactory.<YOUR_DOMAIN>/artifactory/api/npm/npm-airlock/
#   - maven-airlock: https://artifactory.<YOUR_DOMAIN>/artifactory/maven-airlock
#   - pypi-airlock: https://artifactory.<YOUR_DOMAIN>/artifactory/api/pypi/pypi-airlock/simple
#   - docker-airlock: docker-airlock.artifactory.<YOUR_DOMAIN>
#
# Returns:
#   - "available:<repo-url>" if found
#   - "not_found" if not found in any repository
#   - "error:<message>" on error
#

set -e

# Configuration
NPM_REPO="https://artifactory.<YOUR_DOMAIN>/artifactory/api/npm/npm-airlock/"
MAVEN_REPO="https://artifactory.<YOUR_DOMAIN>/artifactory/maven-airlock"
PYPI_REPO="https://artifactory.<YOUR_DOMAIN>/artifactory/api/pypi/pypi-airlock/simple"
DOCKER_REPO="docker-airlock.artifactory.<YOUR_DOMAIN>"

# Default values
PACKAGE=""
LANGUAGE=""
VERSION=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --package)
            PACKAGE="$2"
            shift 2
            ;;
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 --package <name> --language <lang> [--version <version>]"
            echo ""
            echo "Options:"
            echo "  --package   Package name (required)"
            echo "  --language  javascript, java, python, go, docker (required)"
            echo "  --version   Package version (optional)"
            echo "  -h, --help  Show this help message"
            echo ""
            echo "Output:"
            echo "  available:<repo-url>  Package found in repository"
            echo "  not_found             Package not found in any repository"
            echo "  error:<message>       Error occurred"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage."
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$PACKAGE" ]]; then
    echo "error:package_name_required"
    exit 1
fi

if [[ -z "$LANGUAGE" ]]; then
    echo "error:language_required"
    exit 1
fi

# Check package based on language/ecosystem
check_package() {
    local pkg="$1"
    local lang="$2"
    local ver="$3"

    case "$lang" in
        javascript|npm|node)
            # Check npm registry
            # URL format: https://artifactory.<YOUR_DOMAIN>/artifactory/api/npm/npm-airlock/<package>
            local npm_url="${NPM_REPO}${pkg}"
            if curl --silent --head --fail --max-time 10 "$npm_url" >/dev/null 2>&1; then
                echo "available:${NPM_REPO}"
                return 0
            fi
            ;;

        java|maven|gradle)
            # Check Maven repository
            # Maven uses group/artifact/version structure
            # For simplicity, check if package name contains group info or search root
            local maven_pkg="${pkg//.//}"  # Convert dots to slashes for group ID
            local maven_url="${MAVEN_REPO}/${maven_pkg}"
            if curl --silent --head --fail --max-time 10 "$maven_url" >/dev/null 2>&1; then
                echo "available:${MAVEN_REPO}"
                return 0
            fi
            # Also try with hyphens
            maven_pkg="${pkg//-//}"
            maven_url="${MAVEN_REPO}/${maven_pkg}"
            if curl --silent --head --fail --max-time 10 "$maven_url" >/dev/null 2>&1; then
                echo "available:${MAVEN_REPO}"
                return 0
            fi
            ;;

        python|pip)
            # Check PyPI registry
            # URL format: https://artifactory.<YOUR_DOMAIN>/artifactory/api/pypi/pypi-airlock/simple/<package>/
            local pypi_url="${PYPI_REPO}/${pkg}/"
            if curl --silent --head --fail --max-time 10 "$pypi_url" >/dev/null 2>&1; then
                echo "available:${PYPI_REPO}"
                return 0
            fi
            ;;

        docker|container)
            # Check Docker registry
            # This is more complex - would need to use docker CLI or registry API
            # For now, do a simple check against the registry API
            local docker_api_url="https://${DOCKER_REPO}/v2/${pkg}/tags/list"
            if curl --silent --head --fail --max-time 10 "$docker_api_url" >/dev/null 2>&1; then
                echo "available:${DOCKER_REPO}"
                return 0
            fi
            ;;

        go)
            # Go modules - would need proxy check
            # For now, return not_found as we don't have a Go proxy configured
            echo "not_found"
            return 0
            ;;

        *)
            echo "error:unsupported_language"
            return 1
            ;;
    esac

    echo "not_found"
    return 0
}

# Run the check
check_package "$PACKAGE" "$LANGUAGE" "$VERSION"

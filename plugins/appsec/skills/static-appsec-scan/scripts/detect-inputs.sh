#!/bin/bash
#
# detect-inputs.sh — Auto-detect scan inputs based on repository contents
#
# Usage:
#   ./detect-inputs.sh [project-path] [--interactive]
#
# Outputs a JSON object with detected values:
#   {"language": "javascript", "source_path": ".", "dockerfile_count": 2, "dockerfiles": ["Dockerfile", "services/api/Dockerfile"]}
#
# Modes:
#   - Default (no flags): Non-interactive, returns ALL Dockerfiles found
#   - --interactive: Prompts user to confirm each Dockerfile (for manual runs)
#   - --dockerfiles <path1>,<path2>: Returns only specified Dockerfiles

set -e

PROJECT_ROOT="${1:-.}"
INTERACTIVE=false
DOCKERFILES_INPUT=""

# Parse optional arguments
shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --interactive)
            INTERACTIVE=true
            shift
            ;;
        --dockerfiles)
            DOCKERFILES_INPUT="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Detect all programming languages present in the repository
detect_all_languages() {
    local languages=()

    # Check for JavaScript/Node.js
    if [[ -f "$PROJECT_ROOT/package.json" ]] || [[ -f "$PROJECT_ROOT/yarn.lock" ]] || [[ -f "$PROJECT_ROOT/package-lock.json" ]] || \
       find "$PROJECT_ROOT" -maxdepth 5 -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" 2>/dev/null | head -1 | grep -q .; then
        languages+=("javascript")
    fi

    # Check for Java/Maven
    if [[ -f "$PROJECT_ROOT/pom.xml" ]] || \
       find "$PROJECT_ROOT" -maxdepth 5 -name "*.java" 2>/dev/null | head -1 | grep -q .; then
        languages+=("maven")
    fi

    # Check for Java/Gradle
    if [[ -f "$PROJECT_ROOT/build.gradle" ]] || [[ -f "$PROJECT_ROOT/build.gradle.kts" ]] || [[ -f "$PROJECT_ROOT/settings.gradle" ]]; then
        languages+=("gradle")
    fi

    # Check for Python (including UV package manager)
    if [[ -f "$PROJECT_ROOT/requirements.txt" ]] || [[ -f "$PROJECT_ROOT/setup.py" ]] || [[ -f "$PROJECT_ROOT/pyproject.toml" ]] || \
       [[ -f "$PROJECT_ROOT/Pipfile" ]] || [[ -f "$PROJECT_ROOT/uv.lock" ]] || \
       find "$PROJECT_ROOT" -maxdepth 5 -name "*.py" 2>/dev/null | head -1 | grep -q .; then
        languages+=("python")
    fi

    # Check for Go
    if [[ -f "$PROJECT_ROOT/go.mod" ]] || [[ -f "$PROJECT_ROOT/go.sum" ]] || \
       find "$PROJECT_ROOT" -maxdepth 5 -name "*.go" 2>/dev/null | head -1 | grep -q .; then
        languages+=("go")
    fi

    # If no languages detected, default to javascript
    if [[ ${#languages[@]} -eq 0 ]]; then
        languages+=("javascript")
    fi

    # Output all detected languages as newline-separated list
    for lang in "${languages[@]}"; do
        echo "$lang"
    done
}

# Detect programming language (returns first detected, kept for backward compatibility)
detect_language() {
    local lang=""

    # Check for JavaScript/Node.js
    if [[ -f "$PROJECT_ROOT/package.json" ]]; then
        lang="javascript"
    elif [[ -f "$PROJECT_ROOT/yarn.lock" ]] || [[ -f "$PROJECT_ROOT/package-lock.json" ]]; then
        lang="javascript"
    # Check for Java/Maven
    elif [[ -f "$PROJECT_ROOT/pom.xml" ]]; then
        lang="maven"
    # Check for Java/Gradle
    elif [[ -f "$PROJECT_ROOT/build.gradle" ]] || [[ -f "$PROJECT_ROOT/build.gradle.kts" ]] || [[ -f "$PROJECT_ROOT/settings.gradle" ]]; then
        lang="gradle"
    # Check for Python (including UV package manager)
    elif [[ -f "$PROJECT_ROOT/requirements.txt" ]] || [[ -f "$PROJECT_ROOT/setup.py" ]] || [[ -f "$PROJECT_ROOT/pyproject.toml" ]] || [[ -f "$PROJECT_ROOT/Pipfile" ]] || [[ -f "$PROJECT_ROOT/uv.lock" ]]; then
        lang="python"
    # Check for Go
    elif [[ -f "$PROJECT_ROOT/go.mod" ]] || [[ -f "$PROJECT_ROOT/go.sum" ]]; then
        lang="go"
    # Fallback: check for file extensions (search deeper for monorepo structures)
    elif find "$PROJECT_ROOT" -maxdepth 5 -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" 2>/dev/null | head -1 | grep -q .; then
        lang="javascript"
    elif find "$PROJECT_ROOT" -maxdepth 5 -name "*.py" 2>/dev/null | head -1 | grep -q .; then
        lang="python"
    elif find "$PROJECT_ROOT" -maxdepth 5 -name "*.java" 2>/dev/null | head -1 | grep -q .; then
        lang="maven"
    elif find "$PROJECT_ROOT" -maxdepth 5 -name "*.go" 2>/dev/null | head -1 | grep -q .; then
        lang="go"
    else
        lang="javascript"  # default
    fi

    echo "$lang"
}


# Get source path (usually just root)
detect_source_path() {
    # Check for common source directories
    if [[ -d "$PROJECT_ROOT/src" ]] && [[ ! -f "$PROJECT_ROOT/src/package.json" ]]; then
        echo "src"
    elif [[ -d "$PROJECT_ROOT/app" ]] && [[ ! -f "$PROJECT_ROOT/app/package.json" ]]; then
        echo "app"
    else
        echo "."
    fi
}

# Find all Dockerfiles anywhere in the repository
find_all_dockerfiles() {
    local all_dockerfiles=()

    # Search recursively for any file named Dockerfile (case-insensitive)
    while IFS= read -r file; do
        if [[ -n "$file" ]]; then
            all_dockerfiles+=("${file#$PROJECT_ROOT/}")
        fi
    done < <(find "$PROJECT_ROOT" -type f -iname "dockerfile" 2>/dev/null | sort)

    # Also find Dockerfile.* patterns
    while IFS= read -r file; do
        if [[ -n "$file" ]]; then
            all_dockerfiles+=("${file#$PROJECT_ROOT/}")
        fi
    done < <(find "$PROJECT_ROOT" -type f -iname "dockerfile.*" 2>/dev/null | sort)

    # Output all Dockerfiles as newline-separated list
    for df in "${all_dockerfiles[@]}"; do
        echo "$df"
    done
}

# Detect service directories and their languages
# A service is a directory containing a dependency manifest (package.json, pom.xml, etc.)
detect_services() {
    local services=()

    # Find all package.json files (Node.js services)
    while IFS= read -r pkg_file; do
        if [[ -n "$pkg_file" ]]; then
            local rel_path="${pkg_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            services+=("$service_dir:javascript:$rel_path")
        fi
    done < <(find "$PROJECT_ROOT" -name "package.json" -not -path "*/node_modules/*" -not -path "*/.git/*" 2>/dev/null | sort)

    # Find all pom.xml files (Maven services)
    while IFS= read -r pom_file; do
        if [[ -n "$pom_file" ]]; then
            local rel_path="${pom_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            services+=("$service_dir:maven:$rel_path")
        fi
    done < <(find "$PROJECT_ROOT" -name "pom.xml" -not -path "*/.git/*" 2>/dev/null | sort)

    # Find all build.gradle files (Gradle services)
    while IFS= read -r gradle_file; do
        if [[ -n "$gradle_file" ]]; then
            local rel_path="${gradle_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            services+=("$service_dir:gradle:$rel_path")
        fi
    done < <(find "$PROJECT_ROOT" -name "build.gradle" -not -path "*/.git/*" 2>/dev/null | sort)

    # Find all requirements.txt or pyproject.toml files (Python services)
    while IFS= read -r req_file; do
        if [[ -n "$req_file" ]]; then
            local rel_path="${req_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            services+=("$service_dir:python:$rel_path")
        fi
    done < <(find "$PROJECT_ROOT" -name "requirements.txt" -not -path "*/.git/*" -not -path "*/site-packages/*" 2>/dev/null | sort)

    while IFS= read -r pyproject_file; do
        if [[ -n "$pyproject_file" ]]; then
            local rel_path="${pyproject_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            # Avoid duplicate if requirements.txt already found in same dir
            local already_found=false
            for s in "${services[@]}"; do
                if [[ "$s" == "$service_dir:python:"* ]]; then
                    already_found=true
                    break
                fi
            done
            if [[ "$already_found" == false ]]; then
                services+=("$service_dir:python:$rel_path")
            fi
        fi
    done < <(find "$PROJECT_ROOT" -name "pyproject.toml" -not -path "*/.git/*" 2>/dev/null | sort)

    # Find all go.mod files (Go services)
    while IFS= read -r go_file; do
        if [[ -n "$go_file" ]]; then
            local rel_path="${go_file#$PROJECT_ROOT/}"
            local service_dir=$(dirname "$rel_path")
            if [[ "$service_dir" == "." ]]; then
                service_dir="root"
            fi
            services+=("$service_dir:go:$rel_path")
        fi
    done < <(find "$PROJECT_ROOT" -name "go.mod" -not -path "*/.git/*" 2>/dev/null | sort)

    # Output services as newline-separated list (format: path:language:manifest)
    for svc in "${services[@]}"; do
        echo "$svc"
    done
}

# Prompt user interactively for each Dockerfile
find_dockerfiles_interactive() {
    local all_dockerfiles=()
    local confirmed_dockerfiles=()

    # Get all dockerfiles
    while IFS= read -r df; do
        if [[ -n "$df" ]]; then
            all_dockerfiles+=("$df")
        fi
    done < <(find_all_dockerfiles)

    # If no Dockerfiles found, return empty
    if [[ ${#all_dockerfiles[@]} -eq 0 ]]; then
        return
    fi

    # Prompt user for each Dockerfile (prompts go to stderr, not stdout)
    echo "" >&2
    echo "Found ${#all_dockerfiles[@]} Dockerfile(s):" >&2
    for df in "${all_dockerfiles[@]}"; do
        echo -n "  Scan '$df'? [y/N]: " >&2
        read -r response
        if [[ "$response" == "y" || "$response" == "Y" ]]; then
            confirmed_dockerfiles+=("$df")
        fi
    done

    # Output confirmed Dockerfiles as newline-separated list (to stdout)
    for df in "${confirmed_dockerfiles[@]}"; do
        echo "$df"
    done
}


# Main output
LANGUAGE=$(detect_language)
ALL_LANGUAGES=$(detect_all_languages)
SOURCE_PATH=$(detect_source_path)

# Determine which Dockerfiles to return based on mode
if [[ -n "$DOCKERFILES_INPUT" ]]; then
    # User specified exact Dockerfiles via --dockerfiles flag
    IFS=',' read -ra DOCKERFILES_ARRAY <<< "$DOCKERFILES_INPUT"
elif [[ "$INTERACTIVE" == "true" ]]; then
    # Interactive mode - prompt user
    mapfile -t DOCKERFILES_ARRAY < <(find_dockerfiles_interactive)
else
    # Default: return all Dockerfiles found (non-interactive)
    mapfile -t DOCKERFILES_ARRAY < <(find_all_dockerfiles)
fi

DOCKERFILE_COUNT=${#DOCKERFILES_ARRAY[@]}

# Build JSON array of dockerfiles
DOCKERFILES_JSON="["
first=true
for df in "${DOCKERFILES_ARRAY[@]}"; do
    if [[ -n "$df" ]]; then
        if [[ "$first" == true ]]; then
            DOCKERFILES_JSON+="\"$df\""
            first=false
        else
            DOCKERFILES_JSON+=",\"$df\""
        fi
    fi
done
DOCKERFILES_JSON+="]"

# Build JSON array of all detected languages
LANGUAGES_JSON="["
first=true
while IFS= read -r lang; do
    if [[ -n "$lang" ]]; then
        if [[ "$first" == true ]]; then
            LANGUAGES_JSON+="\"$lang\""
            first=false
        else
            LANGUAGES_JSON+=",\"$lang\""
        fi
    fi
done <<< "$ALL_LANGUAGES"
LANGUAGES_JSON+="]"

# Detect services and build JSON array
mapfile -t SERVICES_ARRAY < <(detect_services)
SERVICE_COUNT=${#SERVICES_ARRAY[@]}

# Build services JSON array
SERVICES_JSON="["
first=true
for svc in "${SERVICES_ARRAY[@]}"; do
    if [[ -n "$svc" ]]; then
        # Parse service: path:language:manifest
        IFS=':' read -r svc_path svc_lang svc_manifest <<< "$svc"
        if [[ "$first" == true ]]; then
            SERVICES_JSON+="{\"path\":\"$svc_path\",\"language\":\"$svc_lang\",\"manifest\":\"$svc_manifest\"}"
            first=false
        else
            SERVICES_JSON+=",{\"path\":\"$svc_path\",\"language\":\"$svc_lang\",\"manifest\":\"$svc_manifest\"}"
        fi
    fi
done
SERVICES_JSON+="]"

# Output as JSON for easy parsing
cat <<EOF
{
  "language": "$LANGUAGE",
  "languages": $LANGUAGES_JSON,
  "language_count": $(echo "$ALL_LANGUAGES" | wc -l),
  "source_path": "$SOURCE_PATH",
  "dockerfile_count": $DOCKERFILE_COUNT,
  "dockerfiles": $DOCKERFILES_JSON,
  "service_count": $SERVICE_COUNT,
  "services": $SERVICES_JSON
}
EOF

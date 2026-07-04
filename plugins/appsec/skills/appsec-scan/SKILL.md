---
name: appsec-scan
description: >
  Run the same security scanners as CI — locally, using identical container images —
  before pushing to GitLab, driven by admin-managed scanner preferences and the
  GitLab CI/CD Catalog (component versions resolved on every run). Categories:
  SAST (Fortify or GitLab Semgrep), Dependency Scanning (GitLab SBOM),
  Secret Detection (GitLab), Container Scanning (GTCS), DAST (CI-referenced) —
  plus legacy Parasoft Jtest, Pylint, ESLint, Scantist SCA, and Trivy scanners.
  Reports findings, then (with approval) creates a fix branch, loops fix→rescan,
  and generates a guided triage plan (.appsec-results/TRIAGE.md) for findings it
  cannot fix, mapped to the GitLab Vulnerability Report dismissal workflow.
  Use when the user says: "appsec scan", "run security scanners", "run Fortify",
  "run Parasoft", "Scantist scan", "Trivy scan", "ESLint security", "Pylint scan",
  "pre-push security check", "CI security pipeline locally", "mirror CI scanners",
  "container security scan", "SCA scan", "SAST scan", "dependency scan",
  "secret scan", "secret detection", "security before merge", "scan profile",
  "catalog components", "triage plan", "fix security findings".
  Do NOT activate for general code review, unit testing, or lint-only requests.
---

# AppSec Scan — Catalog-Driven CI Mirror

Run the same scanner images your GitLab CI pipeline uses, locally, so you catch
findings before the push. Which scanner runs for each category is decided by
admin-managed preferences, and component versions are resolved from the GitLab
CI/CD Catalog on every run.

## How this skill is structured

```
skills/appsec-scan/
├── SKILL.md                  ← you are here — orchestration only
├── UPDATE-GUIDE.md           ← maintainer guide (component changes, snapshots)
├── config/
│   ├── scanner-preferences.yaml  ← admin-owned category→scanner profiles
│   └── PREFERENCES.md            ← schema + switching guide
├── scripts/
│   └── catalog.sh            ← CI/CD Catalog resolver (tags, template, README, drift)
├── scanners/                 ← one runner per scanner; each mirrors one CI component
│   ├── fortify-python.sh  fortify-js.sh
│   ├── gitlab-sast.sh     gitlab-dependency-scanning.sh  gitlab-container-scanning.sh
│   ├── secret-detection.sh
│   ├── parasoft-gradle.sh parasoft-maven.sh
│   ├── pylint.sh  eslint.sh  scantist-js.sh  scantist-maven.sh  trivy.sh
│   └── preflight.sh
└── reference/
    └── catalog/              ← vendored component snapshots (offline fallback)
```

**To change which scanner runs for a category:** admins edit
`config/scanner-preferences.yaml` (see `config/PREFERENCES.md`).
**To update a scanner's commands:** edit the file in `scanners/`. Do not edit SKILL.md.
**To add a language variant:** add a file in `scanners/`, add one detection block
in Step 4 below. See UPDATE-GUIDE.md.

---

## Prerequisites

Company profile: tenants must configure `npm`/`pip` and container image pulls to
their internal JFrog virtual repos. The only network endpoint this skill itself
contacts is the active profile's `gitlab_instance` (catalog metadata; offline
fallback snapshots are vendored under `reference/catalog/`).

| Variable | Description | Default |
|---|---|---|
| `APPSEC_PROFILE` | Active preferences profile | `default_profile` from config |
| `APPSEC_REGISTRY` | Registry prefix for company scanner images | `registry.company.com/security` |
| `FORTIFY_PY_IMAGE` | Fortify image for Python (e.g. `fortify-sast:latest-jdk17`) | — |
| `FORTIFY_JS_IMAGE` | Fortify image for JS/TS | — |
| `PARASOFT_IMAGE` | Parasoft Jtest image (shared for Gradle and Maven) | — |
| `PYLINT_IMAGE` | Pylint image (with pylint + pylint2sarif installed) | — |
| `ESLINT_IMAGE` | ESLint image (with npm/npx) | — |
| `SCANTIST_IMAGE` | Scantist image (with Java + curl + sudo) | — |
| `TRIVY_IMAGE` | Trivy image | — |
| `SECRET_DETECTION_IMAGE` | Full GitLab Secret Detection analyzer image override | — |
| `SECRET_DETECTION_IMAGE_PREFIX` | Registry prefix for the `secrets` analyzer | profile-dependent |
| `SECRET_DETECTION_IMAGE_TAG` | Secret Detection analyzer major tag | catalog-resolved, else `7` |
| `SECRET_DETECTION_IMAGE_SUFFIX` | Optional image suffix such as `-fips` | — |
| `SECRET_DETECTION_EXCLUDED_PATHS` | Paths excluded by the analyzer | — |
| `GITLAB_SAST_IMAGE` | Full GitLab SAST (Semgrep) analyzer image override | — |
| `GITLAB_SAST_IMAGE_PREFIX` / `GITLAB_SAST_IMAGE_TAG` | Semgrep analyzer prefix/tag | profile-dependent / catalog-resolved, else `6` |
| `GITLAB_DS_IMAGE` | Full GitLab Dependency Scanning analyzer image override | — |
| `GITLAB_DS_IMAGE_PREFIX` / `GITLAB_DS_IMAGE_TAG` | DS analyzer prefix/tag | profile-dependent / catalog-resolved, else `2` |
| `GITLAB_CS_IMAGE` | Full GitLab Container Scanning analyzer image override | — |
| `GITLAB_CS_IMAGE_PREFIX` / `GITLAB_CS_IMAGE_TAG` | CS analyzer prefix/tag | profile-dependent / catalog-resolved, else `8` |
| `CS_IMAGE` | Container image:tag for Container Scanning to scan | — |
| `DEVSECOPS_IMPORT_URL` | DTP server URL for Scantist JAR download | — |
| `APP_NAME` | Application name used in Fortify build IDs | `basename $PWD` |
| `SOURCE_PATH` | Source directory passed to Fortify and Pylint | `src` |
| `ESLINT_CONFIG_FILE` | Path to ESLint config file | — |
| `MAVEN_SETTINGS_XML` | Maven settings.xml (Parasoft Maven + Scantist Maven) | — |
| `TRIVY_TARGET` | Container image:tag to scan with Trivy | — |
| `CI_PROJECT_URL` | GitLab project URL (Parasoft source control config) | — |

Company-profile shell setup (`~/.bashrc` / `~/.zshrc`):

```bash
export APPSEC_REGISTRY="registry.company.com/security"
export DEVSECOPS_IMPORT_URL="https://dtp.company.com"
export FORTIFY_PY_IMAGE="fortify-sast:latest-jdk17"
export FORTIFY_JS_IMAGE="fortify-sast:latest-jdk17"
export PARASOFT_IMAGE="parasoft-jtest:latest-jdk17"
export PYLINT_IMAGE="pylint-scanner:latest"
export ESLINT_IMAGE="eslint-scanner:latest-node20"
export SCANTIST_IMAGE="scantist-scanner:latest"
export TRIVY_IMAGE="trivy-scanner:latest"
```

---

## Step 1 — Locate the skill's directories

The scanner scripts are relative to the skill's own directory, not the project
being scanned. Resolve this path first — subsequent steps depend on it.

```bash
# SKILL_DIR is the absolute path to skills/appsec-scan/
# Adjust this path if your plugin is installed at a different location.
SKILL_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
SCANNERS_DIR="$SKILL_DIR/scanners"
SCRIPTS_DIR="$SKILL_DIR/scripts"

if [ ! -d "$SCANNERS_DIR" ] || [ ! -d "$SCRIPTS_DIR" ]; then
  echo "ERROR: scanners/ or scripts/ not found under $SKILL_DIR"
  echo "Ensure the full appsec-scan skill directory is present, not just SKILL.md"
  exit 1
fi
```

---

## Step 1.5 — Load scanner preferences (Claude reads the YAML)

Read `config/scanner-preferences.yaml` from `$SKILL_DIR` with the Read tool and
resolve the active profile yourself — do not shell out to a YAML parser:

1. Active profile = `$APPSEC_PROFILE` if set, else the file's `default_profile`.
   If the profile does not exist, stop and tell the user which profiles are
   available.
2. From the active profile extract: `gitlab_instance`, `catalog_auth`, each
   category's `components` / `runners` / `enabled`, and the
   `additional_scanners` keys.
3. Export the results as shell variables for the following steps:

```bash
APPSEC_PROFILE="${APPSEC_PROFILE:-company}"   # ← replace with resolved profile name
GITLAB_INSTANCE="https://gitlab.company.com"  # ← from profile
CATALOG_AUTH_ENV=""                            # ← env var NAME from catalog_auth, or empty for none

# One RUN_* flag per category runner + one per additional scanner, from the profile:
RUN_FORTIFY=false; RUN_GITLAB_SAST=false; RUN_GITLAB_DS=false
RUN_SECRET_DETECTION=false; RUN_GITLAB_CS=false
RUN_PARASOFT=false; RUN_PYLINT=false; RUN_ESLINT=false; RUN_SCANTIST=false; RUN_TRIVY=false
# Set each to true when the active profile's category is enabled and lists the
# matching runner (e.g. sast → fortify-*.sh ⇒ RUN_FORTIFY, sast → gitlab-sast.sh
# ⇒ RUN_GITLAB_SAST), or when the additional_scanners key is present.

echo "Profile: $APPSEC_PROFILE   GitLab: $GITLAB_INSTANCE"
```

4. Image prefixes for the GitLab analyzers default per profile:
   `public-test` → `registry.gitlab.com/security-products`;
   `company` → `$APPSEC_REGISTRY`. Explicit `*_IMAGE_PREFIX`/`*_IMAGE` env vars
   always win.

---

## Step 2 — Preflight: validate required environment

Runs `scanners/preflight.sh` in its own process — a real shell script that is
shellchecked and can be run standalone.

```bash
CATALOG_AUTH_ENV="$CATALOG_AUTH_ENV" bash "$SCANNERS_DIR/preflight.sh" || return 1
```

---

## Step 2.5 — Resolve CI/CD Catalog components (every run)

For every **enabled** category component in the active profile, resolve the
component against the catalog and check drift. `scripts/catalog.sh` is the only
thing that talks to the network, and only to `$GITLAB_INSTANCE`; when offline it
falls back to the vendored snapshots in `reference/catalog/` and says so.

```bash
CATALOG_CACHE=".appsec-results/catalog"
mkdir -p "$CATALOG_CACHE"

# Repeat for each enabled category component (from Step 1.5), pairing each
# component with its runner script (or "none"):
bash "$SCRIPTS_DIR/catalog.sh" resolve "$GITLAB_INSTANCE" "components/sast/sast" "$CATALOG_CACHE" "$CATALOG_AUTH_ENV"
bash "$SCRIPTS_DIR/catalog.sh" check-drift "components/sast/sast" "$CATALOG_CACHE" "$SCANNERS_DIR/gitlab-sast.sh"
```

Then present the user a resolution table before scanning:

| Category | Component | Version | Source | Drift |
|---|---|---|---|---|
| sast | components/sast/sast | 3.4.0 | online | — |

- `resolve` prints `<component>@<tag> [online|offline-fallback]` and logs which
  tags were considered and why one was chosen (highest stable release).
- `check-drift` prints `DRIFT:` lines when the component's defaults have moved
  ahead of the local runner — surface these to the user verbatim.
- Read each resolved `template.yml` in the cache and use its `image_tag` input
  default as the analyzer tag for Step 4 (offline: keep the runner's documented
  fallback). The cached `README.md` is the component's official guide — offer to
  summarize it if the user wants details on any component.

---

## Step 3 — Detect project type and set defaults

```bash
APP_NAME="${APP_NAME:-$(basename "$PWD")}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SOURCE_PATH="${SOURCE_PATH:-src}"
CI_PROJECT_DIR="${CI_PROJECT_DIR:-$PWD}"
APPSEC_REGISTRY="${APPSEC_REGISTRY:-registry.company.com/security}"

# GitLab analyzer images — prefix per profile (Step 1.5), tag from Step 2.5:
GITLAB_ANALYZER_PREFIX_DEFAULT="registry.gitlab.com/security-products"
[ "$APPSEC_PROFILE" = "company" ] && GITLAB_ANALYZER_PREFIX_DEFAULT="$APPSEC_REGISTRY"
SECRET_DETECTION_IMAGE_PREFIX="${SECRET_DETECTION_IMAGE_PREFIX:-$GITLAB_ANALYZER_PREFIX_DEFAULT}"
SECRET_DETECTION_IMAGE_TAG="${SECRET_DETECTION_IMAGE_TAG:-7}"          # ← catalog-resolved when online
SECRET_DETECTION_IMAGE_SUFFIX="${SECRET_DETECTION_IMAGE_SUFFIX:-}"
SECRET_DETECTION_IMAGE="${SECRET_DETECTION_IMAGE:-${SECRET_DETECTION_IMAGE_PREFIX}/secrets:${SECRET_DETECTION_IMAGE_TAG}${SECRET_DETECTION_IMAGE_SUFFIX}}"
GITLAB_SAST_IMAGE_PREFIX="${GITLAB_SAST_IMAGE_PREFIX:-$GITLAB_ANALYZER_PREFIX_DEFAULT}"
GITLAB_SAST_IMAGE_TAG="${GITLAB_SAST_IMAGE_TAG:-6}"                    # ← catalog-resolved when online
GITLAB_SAST_IMAGE="${GITLAB_SAST_IMAGE:-${GITLAB_SAST_IMAGE_PREFIX}/semgrep:${GITLAB_SAST_IMAGE_TAG}}"
GITLAB_DS_IMAGE_PREFIX="${GITLAB_DS_IMAGE_PREFIX:-$GITLAB_ANALYZER_PREFIX_DEFAULT}"
GITLAB_DS_IMAGE_TAG="${GITLAB_DS_IMAGE_TAG:-2}"                        # ← catalog-resolved when online
GITLAB_DS_IMAGE="${GITLAB_DS_IMAGE:-${GITLAB_DS_IMAGE_PREFIX}/dependency-scanning:${GITLAB_DS_IMAGE_TAG}}"
GITLAB_CS_IMAGE_PREFIX="${GITLAB_CS_IMAGE_PREFIX:-$GITLAB_ANALYZER_PREFIX_DEFAULT}"
GITLAB_CS_IMAGE_TAG="${GITLAB_CS_IMAGE_TAG:-8}"                        # ← catalog-resolved when online
GITLAB_CS_IMAGE="${GITLAB_CS_IMAGE:-${GITLAB_CS_IMAGE_PREFIX}/container-scanning:${GITLAB_CS_IMAGE_TAG}}"

FORTIFY_PY_PID=""; FORTIFY_JS_PID=""; PYLINT_PID=""; ESLINT_PID=""; SCANTIST_JS_PID=""
SECRET_DETECTION_PID=""; GITLAB_SAST_PID=""; GITLAB_DS_PID=""; GITLAB_CS_PID=""

HAS_POM=false; HAS_GRADLE=false; HAS_PACKAGE_JSON=false
HAS_REQUIREMENTS=false; HAS_DOCKERFILE=false
[ -f pom.xml ]                                         && HAS_POM=true
{ [ -f build.gradle ] || [ -f build.gradle.kts ]; }   && HAS_GRADLE=true
[ -f package.json ]                                    && HAS_PACKAGE_JSON=true
{ [ -f requirements.txt ] || [ -f pyproject.toml ]; } && HAS_REQUIREMENTS=true
[ -f Dockerfile ]                                      && HAS_DOCKERFILE=true

echo "Project: $APP_NAME  Branch: $BRANCH"
echo "Detected: Maven=$HAS_POM Gradle=$HAS_GRADLE NPM=$HAS_PACKAGE_JSON Python=$HAS_REQUIREMENTS Docker=$HAS_DOCKERFILE"

mkdir -p .appsec-results
grep -qxF '.appsec-results/' .gitignore 2>/dev/null || \
  echo "Reminder: add .appsec-results/ to .gitignore"
```

---

## Step 4 — Run applicable scanners

Each scanner script is mounted read-only into its container at `/runner.sh`.
The container executes the runner with `bash` or `sh`, depending on the analyzer
image. All output paths inside the script use `/workspace/...` which maps to
`$PWD` on the host.

Run a category block only when its `RUN_*` flag from Step 1.5 is true; legacy
`additional_scanners` blocks additionally require their image env vars (v1
behavior). Run the parallel scanners first (background `&`), then the
sequential ones.

### Fortify SAST — Python
*Category: sast (company). Applies when: Python project detected. Runner: `scanners/fortify-python.sh`.*

```bash
if $RUN_FORTIFY && $HAS_REQUIREMENTS && [ -n "${FORTIFY_PY_IMAGE:-}" ]; then
  echo "[Fortify/Python] Starting in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/fortify-python.sh:/runner.sh:ro" \
    -w /workspace \
    -e APP_NAME="$APP_NAME" \
    -e SOURCE_PATH="$SOURCE_PATH" \
    "${APPSEC_REGISTRY}/${FORTIFY_PY_IMAGE:-}" \
    bash /runner.sh > .appsec-results/fortify-python.log 2>&1 &
  FORTIFY_PY_PID=$!
fi
```

### Fortify SAST — JS/TS
*Category: sast (company). Applies when: JS/TS project detected. Runner: `scanners/fortify-js.sh`.*

```bash
if $RUN_FORTIFY && $HAS_PACKAGE_JSON && [ -n "${FORTIFY_JS_IMAGE:-}" ]; then
  echo "[Fortify/JS] Starting in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/fortify-js.sh:/runner.sh:ro" \
    -w /workspace \
    -e APP_NAME="$APP_NAME" \
    -e SOURCE_PATH="$SOURCE_PATH" \
    "${APPSEC_REGISTRY}/${FORTIFY_JS_IMAGE:-}" \
    bash /runner.sh > .appsec-results/fortify-js.log 2>&1 &
  FORTIFY_JS_PID=$!
fi
```

### GitLab SAST (Semgrep)
*Category: sast (public-test, or any profile that selects `gitlab-sast.sh`).
Language-agnostic. Runner: `scanners/gitlab-sast.sh`.*

```bash
if $RUN_GITLAB_SAST && [ -n "${GITLAB_SAST_IMAGE:-}" ]; then
  echo "[GitLab SAST] Pulling ${GITLAB_SAST_IMAGE}..."
  if docker pull "${GITLAB_SAST_IMAGE}"; then
    echo "[GitLab SAST] Starting in background..."
    docker run --rm \
      --entrypoint "" \
      -v "$PWD:/workspace" \
      -v "$SCANNERS_DIR/gitlab-sast.sh:/runner.sh:ro" \
      -w /workspace \
      -e CI_PROJECT_DIR="/workspace" \
      -e SAST_EXCLUDED_PATHS="${SAST_EXCLUDED_PATHS:-}" \
      "${GITLAB_SAST_IMAGE}" \
      sh /runner.sh > .appsec-results/gitlab-sast.log 2>&1 &
    GITLAB_SAST_PID=$!
  else
    echo "[GitLab SAST] Failed to pull ${GITLAB_SAST_IMAGE}; skipping scan"
  fi
fi
```

### GitLab Dependency Scanning (SBOM)
*Category: dependency_scanning. Generates an SBOM locally; vulnerability
matching happens in GitLab after push. Requires a lock file (package-lock.json,
poetry.lock, pip-compile output, …). Runner: `scanners/gitlab-dependency-scanning.sh`.*

```bash
if $RUN_GITLAB_DS && [ -n "${GITLAB_DS_IMAGE:-}" ]; then
  echo "[GitLab DS] Pulling ${GITLAB_DS_IMAGE}..."
  if docker pull "${GITLAB_DS_IMAGE}"; then
    echo "[GitLab DS] Starting in background..."
    docker run --rm \
      --entrypoint "" \
      -v "$PWD:/workspace" \
      -v "$SCANNERS_DIR/gitlab-dependency-scanning.sh:/runner.sh:ro" \
      -w /workspace \
      -e CI_PROJECT_DIR="/workspace" \
      -e GITLAB_FEATURES="dependency_scanning" \
      "${GITLAB_DS_IMAGE}" \
      sh /runner.sh > .appsec-results/gitlab-ds.log 2>&1 &
    GITLAB_DS_PID=$!
  else
    echo "[GitLab DS] Failed to pull ${GITLAB_DS_IMAGE}; skipping scan"
  fi
fi
```

`GITLAB_FEATURES=dependency_scanning` mirrors the licensed CI environment your
org's GitLab Ultimate subscription provides in pipelines; without it the
analyzer refuses to start.

### GitLab Secret Detection
*Category: secret_detection. Runs for any Git repository. Runner:
`scanners/secret-detection.sh`. Mirrors the GitLab CI/CD Catalog component
image shape and `/analyzer run` script.*

```bash
if $RUN_SECRET_DETECTION && git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ -n "${SECRET_DETECTION_IMAGE:-}" ]; then
  echo "[Secret Detection] Pulling ${SECRET_DETECTION_IMAGE}..."
  if docker pull "${SECRET_DETECTION_IMAGE}"; then
    echo "[Secret Detection] Starting in background..."
    docker run --rm \
      --entrypoint "" \
      -v "$PWD:/workspace" \
      -v "$SCANNERS_DIR/secret-detection.sh:/runner.sh:ro" \
      -w /workspace \
      -e CI_PROJECT_DIR="/workspace" \
      -e GIT_DEPTH="${GIT_DEPTH:-50}" \
      -e SECRET_DETECTION_EXCLUDED_PATHS="${SECRET_DETECTION_EXCLUDED_PATHS:-}" \
      "${SECRET_DETECTION_IMAGE}" \
      sh /runner.sh > .appsec-results/secret-detection.log 2>&1 &
    SECRET_DETECTION_PID=$!
  else
    echo "[Secret Detection] Failed to pull ${SECRET_DETECTION_IMAGE}; skipping scan"
  fi
else
  echo "[Secret Detection] Skipped — disabled in profile, not a git worktree, or image unset"
fi
```

### GitLab Container Scanning (GTCS)
*Category: container_scanning. Scans the image named by `CS_IMAGE` (or
`CI_APPLICATION_REPOSITORY` + `CI_APPLICATION_TAG`). Runner:
`scanners/gitlab-container-scanning.sh`.*

```bash
if $RUN_GITLAB_CS && [ -n "${CS_IMAGE:-}${CI_APPLICATION_REPOSITORY:-}" ] && [ -n "${GITLAB_CS_IMAGE:-}" ]; then
  echo "[GitLab CS] Pulling ${GITLAB_CS_IMAGE}..."
  if docker pull "${GITLAB_CS_IMAGE}"; then
    echo "[GitLab CS] Starting in background..."
    docker run --rm \
      --entrypoint "" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$PWD:/workspace" \
      -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
      -w /workspace \
      -e CI_PROJECT_DIR="/workspace" \
      -e CS_IMAGE="${CS_IMAGE:-}" \
      -e CI_APPLICATION_REPOSITORY="${CI_APPLICATION_REPOSITORY:-}" \
      -e CI_APPLICATION_TAG="${CI_APPLICATION_TAG:-}" \
      "${GITLAB_CS_IMAGE}" \
      sh /runner.sh > .appsec-results/gitlab-cs.log 2>&1 &
    GITLAB_CS_PID=$!
  else
    echo "[GitLab CS] Failed to pull ${GITLAB_CS_IMAGE}; skipping scan"
  fi
elif $RUN_GITLAB_CS; then
  echo "[GitLab CS] Skipped — set CS_IMAGE=<image:tag> to scan a container image"
fi
```

### Pylint
*Additional scanner. Applies when: Python project. Entrypoint overridden to `""`. Runner: `scanners/pylint.sh`.*

```bash
if $RUN_PYLINT && $HAS_REQUIREMENTS && [ -n "${PYLINT_IMAGE:-}" ]; then
  echo "[Pylint] Starting in background..."
  docker run --rm \
    --entrypoint "" \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/pylint.sh:/runner.sh:ro" \
    -w /workspace \
    -e SOURCE_PATH="$SOURCE_PATH" \
    "${APPSEC_REGISTRY}/${PYLINT_IMAGE:-}" \
    bash /runner.sh > .appsec-results/pylint.log 2>&1 &
  PYLINT_PID=$!
fi
```

### ESLint
*Additional scanner. Applies when: JS/TS project and `ESLINT_CONFIG_FILE` is set. Runner: `scanners/eslint.sh`.*

```bash
if $RUN_ESLINT && $HAS_PACKAGE_JSON && [ -n "${ESLINT_IMAGE:-}" ] && [ -n "${ESLINT_CONFIG_FILE:-}" ]; then
  echo "[ESLint] Starting in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/eslint.sh:/runner.sh:ro" \
    -w /workspace \
    -e ESLINT_CONFIG_FILE="${ESLINT_CONFIG_FILE:-}" \
    "${APPSEC_REGISTRY}/${ESLINT_IMAGE:-}" \
    bash /runner.sh > .appsec-results/eslint.log 2>&1 &
  ESLINT_PID=$!
fi
```

### Scantist SCA — JS
*Additional scanner. Applies when: JS/TS project. Needs `--network=host` to reach DTP. Runner: `scanners/scantist-js.sh`.*

```bash
if $RUN_SCANTIST && $HAS_PACKAGE_JSON && [ -n "${SCANTIST_IMAGE:-}" ] && [ -n "${DEVSECOPS_IMPORT_URL:-}" ]; then
  echo "[Scantist/JS] Starting in background..."
  docker run --rm \
    --network=host \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/scantist-js.sh:/runner.sh:ro" \
    -w /workspace \
    -e DEVSECOPS_IMPORT_URL="${DEVSECOPS_IMPORT_URL:-}" \
    -e BRANCH="$BRANCH" \
    "${APPSEC_REGISTRY}/${SCANTIST_IMAGE:-}" \
    bash /runner.sh > .appsec-results/scantist-js.log 2>&1 &
  SCANTIST_JS_PID=$!
fi
```

### Wait for all parallel scanners

```bash
echo "Waiting for parallel scanners..."
for pid_var in FORTIFY_PY_PID FORTIFY_JS_PID PYLINT_PID ESLINT_PID SCANTIST_JS_PID \
               SECRET_DETECTION_PID GITLAB_SAST_PID GITLAB_DS_PID GITLAB_CS_PID; do
  pid="${!pid_var:-}"
  if [ -n "$pid" ]; then
    if wait "$pid"; then
      echo "[${pid_var/_PID/}] Done"
    else
      rc=$?
      if [ "$pid_var" = "GITLAB_DS_PID" ] && [ "$rc" -eq 2 ]; then
        echo "[GITLAB_DS] Local run unsupported by this analyzer — run Dependency Scanning in the CI pipeline"
      else
        echo "[${pid_var/_PID/}] Failed — check .appsec-results/ for logs"
      fi
    fi
  fi
done
```

### Parasoft Jtest — Gradle
*Additional scanner, sequential. Applies when: Gradle project. Runner: `scanners/parasoft-gradle.sh`.*

```bash
if $RUN_PARASOFT && $HAS_GRADLE && [ -n "${PARASOFT_IMAGE:-}" ]; then
  echo "[Parasoft/Gradle] Running..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/parasoft-gradle.sh:/runner.sh:ro" \
    -w /workspace \
    -e BRANCH="$BRANCH" \
    -e CI_PROJECT_URL="${CI_PROJECT_URL:-$(git remote get-url origin 2>/dev/null || echo local)}" \
    -e CI_PROJECT_DIR="/workspace" \
    "${APPSEC_REGISTRY}/${PARASOFT_IMAGE:-}" \
    bash /runner.sh 2>&1 | tee .appsec-results/parasoft-gradle.log
fi
```

### Parasoft Jtest — Maven
*Additional scanner, sequential. Applies when: Maven project (no Gradle). Runner: `scanners/parasoft-maven.sh`.*

```bash
if $RUN_PARASOFT && $HAS_POM && ! $HAS_GRADLE && [ -n "${PARASOFT_IMAGE:-}" ] && [ -n "${MAVEN_SETTINGS_XML:-}" ]; then
  echo "[Parasoft/Maven] Running..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/parasoft-maven.sh:/runner.sh:ro" \
    -w /workspace \
    -e BRANCH="$BRANCH" \
    -e CI_PROJECT_URL="${CI_PROJECT_URL:-$(git remote get-url origin 2>/dev/null || echo local)}" \
    -e CI_PROJECT_DIR="/workspace" \
    -e MAVEN_SETTINGS_XML="${MAVEN_SETTINGS_XML:-}" \
    "${APPSEC_REGISTRY}/${PARASOFT_IMAGE:-}" \
    bash /runner.sh 2>&1 | tee .appsec-results/parasoft-maven.log
fi
```

### Scantist SCA — Maven
*Additional scanner, sequential — runs after Parasoft Maven (needs compiled artifacts). Runner: `scanners/scantist-maven.sh`.*

```bash
if $RUN_SCANTIST && $HAS_POM && ! $HAS_GRADLE && [ -n "${SCANTIST_IMAGE:-}" ] && [ -n "${DEVSECOPS_IMPORT_URL:-}" ] && [ -n "${MAVEN_SETTINGS_XML:-}" ]; then
  echo "[Scantist/Maven] Running..."
  docker run --rm \
    --network=host \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/scantist-maven.sh:/runner.sh:ro" \
    -w /workspace \
    -e DEVSECOPS_IMPORT_URL="${DEVSECOPS_IMPORT_URL:-}" \
    -e BRANCH="$BRANCH" \
    -e MAVEN_SETTINGS_XML="${MAVEN_SETTINGS_XML:-}" \
    "${APPSEC_REGISTRY}/${SCANTIST_IMAGE:-}" \
    bash /runner.sh 2>&1 | tee .appsec-results/scantist-maven.log
fi
```

### Trivy — Container image
*Additional scanner. Run if `TRIVY_TARGET` is set. Runner: `scanners/trivy.sh`.*

```bash
if $RUN_TRIVY && [ -n "${TRIVY_TARGET:-}" ] && [ -n "${TRIVY_IMAGE:-}" ]; then
  echo "[Trivy] Scanning ${TRIVY_TARGET:-}..."
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/trivy.sh:/runner.sh:ro" \
    -e TRIVY_TARGET="${TRIVY_TARGET:-}" \
    "${APPSEC_REGISTRY}/${TRIVY_IMAGE:-}" \
    bash /runner.sh
elif $RUN_TRIVY; then
  echo "[Trivy] Skipped — set TRIVY_TARGET=<image:tag> to enable"
fi
```

---

## Step 5 — Parse results and severity gate

```bash
echo ""
echo "============================================================"
echo "  AppSec Scan Summary   (profile: $APPSEC_PROFILE)"
echo "============================================================"
printf "%-22s %-10s %-6s %-8s %-5s\n" "Scanner" "Critical" "High" "Medium" "Low"
printf "%-22s %-10s %-6s %-8s %-5s\n" "-------" "--------" "----" "------" "---"

TOTAL_CRITICAL=0; TOTAL_HIGH=0
HAS_SUMMARY_UNKNOWN=false

HAS_JQ=true
HAS_UNZIP=true
HAS_XMLLINT=true
command -v jq >/dev/null 2>&1 || HAS_JQ=false
command -v unzip >/dev/null 2>&1 || HAS_UNZIP=false
command -v xmllint >/dev/null 2>&1 || HAS_XMLLINT=false

if ! $HAS_JQ || ! $HAS_UNZIP || ! $HAS_XMLLINT; then
  echo "WARNING: One or more summary parsers are unavailable; some counts may show as UNKNOWN."
  ! $HAS_JQ && echo "  - jq not found: Pylint, ESLint, Secret Detection, GitLab SAST/DS/CS, and Trivy counts may be unavailable."
  ! $HAS_UNZIP && echo "  - unzip not found: Fortify FPR counts may be unavailable."
  ! $HAS_XMLLINT && echo "  - xmllint not found: Parasoft XML counts may be unavailable."
fi

print_missing_report() {
  printf "%-22s %s\n" "$1" "WARNING: report file not present"
}

print_unknown_report() {
  printf "%-22s %s\n" "$1" "UNKNOWN (failed to parse report)"
  HAS_SUMMARY_UNKNOWN=true
}

# Shared parser for GitLab security report JSON (.vulnerabilities[].severity)
print_gl_report() {  # $1=label  $2=report-file  $3=count-into-totals(true/false)
  if [ ! -f "$2" ]; then print_missing_report "$1"; return 0; fi
  if ! $HAS_JQ; then print_unknown_report "$1"; return 0; fi
  local crit high med low
  if crit=$(jq '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "critical")] | length' "$2" 2>/dev/null) && \
     high=$(jq '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "high")] | length' "$2" 2>/dev/null) && \
     med=$(jq  '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "medium")] | length' "$2" 2>/dev/null) && \
     low=$(jq  '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "low")] | length' "$2" 2>/dev/null); then
    printf "%-22s %-10s %-6s %-8s %-5s\n" "$1" "$crit" "$high" "$med" "$low"
    if [ "$3" = "true" ]; then
      TOTAL_CRITICAL=$((TOTAL_CRITICAL + crit)); TOTAL_HIGH=$((TOTAL_HIGH + high))
    fi
  else
    print_unknown_report "$1"
  fi
}

# Fortify: count <Vulnerability> tags in the embedded fvdl
for fpr_label in "fortify-python:Fortify/Python" "fortify-js:Fortify/JS"; do
  fpr_file=".appsec-results/${fpr_label%%:*}.fpr"
  label="${fpr_label##*:}"
  if [ -f "$fpr_file" ]; then
    if ! $HAS_UNZIP; then
      print_unknown_report "$label"
    elif unzip -p "$fpr_file" audit.fvdl >/dev/null 2>&1; then
      count=$(unzip -p "$fpr_file" audit.fvdl 2>/dev/null | grep -c '<Vulnerability>' || true)
      printf "%-22s %-10s\n" "$label" "$count total (see .fpr for severity breakdown)"
    else
      print_unknown_report "$label"
    fi
  else
    print_missing_report "$label"
  fi
done

# GitLab SAST (only when it ran)
[ -n "$GITLAB_SAST_PID" ] && print_gl_report "GitLab SAST" .appsec-results/gl-sast-report.json true

# GitLab Dependency Scanning — SBOM inventory, findings matched server-side
if [ -n "$GITLAB_DS_PID" ]; then
  DS_SBOMS=$(ls .appsec-results/gl-sbom-*.cdx.json 2>/dev/null || true)
  if [ -n "$DS_SBOMS" ] && $HAS_JQ; then
    DS_COMPONENTS=$(jq -s '[.[].components // [] | length] | add' $DS_SBOMS 2>/dev/null || echo "?")
    printf "%-22s %s\n" "GitLab DS" "SBOM: $DS_COMPONENTS components — findings matched by GitLab after push"
  elif grep -q 'no supported lockfile' .appsec-results/gitlab-ds.log 2>/dev/null; then
    printf "%-22s %s\n" "GitLab DS" "no supported lockfile — nothing scanned"
  else
    printf "%-22s %s\n" "GitLab DS" "CI-only (local run unsupported) — see gitlab-ds.log"
  fi
fi

# GitLab Container Scanning (only when it ran)
[ -n "$GITLAB_CS_PID" ] && print_gl_report "GitLab CS" .appsec-results/gl-container-scanning-report.json true

# Pylint — drop the ##tool header line added by pylint.sh before parsing JSON
if [ -f .appsec-results/pylint-report.json ]; then
  if ! $HAS_JQ; then
    print_unknown_report "Pylint"
  else
    PYLINT_JSON=$(grep -v '^##tool' .appsec-results/pylint-report.json || true)
    if PY_ERR=$(printf '%s\n' "$PYLINT_JSON" | jq '[.[] | select(.type=="fatal" or .type=="error")] | length' 2>/dev/null) && \
       PY_WARN=$(printf '%s\n' "$PYLINT_JSON" | jq '[.[] | select(.type=="warning")] | length' 2>/dev/null); then
      printf "%-22s %-10s %-6s\n" "Pylint" "$PY_ERR" "$PY_WARN"
      TOTAL_CRITICAL=$((TOTAL_CRITICAL + PY_ERR))
    else
      print_unknown_report "Pylint"
    fi
  fi
elif $RUN_PYLINT; then
  print_missing_report "Pylint"
fi

# ESLint
if [ -f .appsec-results/eslint.json ]; then
  if ! $HAS_JQ; then
    print_unknown_report "ESLint"
  elif ES_ERR=$(jq '[.[].messages[] | select(.severity==2)] | length' .appsec-results/eslint.json 2>/dev/null) && \
       ES_WARN=$(jq '[.[].messages[] | select(.severity==1)] | length' .appsec-results/eslint.json 2>/dev/null); then
    printf "%-22s %-10s %-6s\n" "ESLint" "$ES_ERR" "$ES_WARN"
    TOTAL_CRITICAL=$((TOTAL_CRITICAL + ES_ERR))
  else
    print_unknown_report "ESLint"
  fi
elif $RUN_ESLINT; then
  print_missing_report "ESLint"
fi

# Parasoft
PARASOFT_REPORT=".appsec-results/parasoft-reports/report.xml"
if [ -f "$PARASOFT_REPORT" ]; then
  if ! $HAS_XMLLINT; then
    print_unknown_report "Parasoft"
  elif PARA_CRIT=$(xmllint --xpath "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=1])" "$PARASOFT_REPORT" 2>/dev/null) && \
       PARA_HIGH=$(xmllint --xpath "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=2])" "$PARASOFT_REPORT" 2>/dev/null) && \
       PARA_MED=$(xmllint --xpath  "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=3])" "$PARASOFT_REPORT" 2>/dev/null) && \
       PARA_LOW=$(xmllint --xpath  "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=4])" "$PARASOFT_REPORT" 2>/dev/null); then
    printf "%-22s %-10s %-6s %-8s %-5s\n" "Parasoft" "$PARA_CRIT" "$PARA_HIGH" "$PARA_MED" "$PARA_LOW"
    TOTAL_CRITICAL=$((TOTAL_CRITICAL + PARA_CRIT)); TOTAL_HIGH=$((TOTAL_HIGH + PARA_HIGH))
  else
    print_unknown_report "Parasoft"
  fi
elif $RUN_PARASOFT; then
  print_missing_report "Parasoft"
fi

# GitLab Secret Detection
if [ -f .appsec-results/gl-secret-detection-report.json ]; then
  if ! $HAS_JQ; then
    print_unknown_report "Secret Detection"
  elif SD_CRIT=$(jq '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "critical")] | length' .appsec-results/gl-secret-detection-report.json 2>/dev/null) && \
       SD_HIGH=$(jq '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "high")] | length' .appsec-results/gl-secret-detection-report.json 2>/dev/null) && \
       SD_MED=$(jq  '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "medium")] | length' .appsec-results/gl-secret-detection-report.json 2>/dev/null) && \
       SD_LOW=$(jq  '[.vulnerabilities[]? | select((.severity // "" | ascii_downcase) == "low")] | length' .appsec-results/gl-secret-detection-report.json 2>/dev/null); then
    printf "%-22s %-10s %-6s %-8s %-5s\n" "Secret Detection" "$SD_CRIT" "$SD_HIGH" "$SD_MED" "$SD_LOW"
    TOTAL_CRITICAL=$((TOTAL_CRITICAL + SD_CRIT)); TOTAL_HIGH=$((TOTAL_HIGH + SD_HIGH))
    if [ "$SD_CRIT" -gt 0 ] || [ "$SD_HIGH" -gt 0 ] || [ "$SD_MED" -gt 0 ] || [ "$SD_LOW" -gt 0 ]; then
      echo ""
      echo "Secret Detection findings (redacted):"
      jq -r '.vulnerabilities[]? | [
        (.severity // "UNKNOWN"),
        (.name // .message // .id // "Secret detected"),
        (.location.file // .location.path // "unknown"),
        ((.location.start_line // .location.line // 0) | tostring)
      ] | @tsv' .appsec-results/gl-secret-detection-report.json |
        awk -F '\t' '{printf "  - [%s] %s at %s:%s\n", $1, $2, $3, $4}'
      echo "  Remediation: rotate or revoke any real credential, remove it from source, and load it from CI/CD variables or a secret manager."
      echo "  Note: removing a secret from the working tree does not revoke it or erase it from git history."
      echo ""
    fi
  else
    print_unknown_report "Secret Detection"
  fi
elif $RUN_SECRET_DETECTION; then
  print_missing_report "Secret Detection"
fi

# Trivy
if [ -f .appsec-results/trivy-results.json ]; then
  if ! $HAS_JQ; then
    print_unknown_report "Trivy"
  elif TRIVY_CRIT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' .appsec-results/trivy-results.json 2>/dev/null) && \
       TRIVY_HIGH=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")]    | length' .appsec-results/trivy-results.json 2>/dev/null) && \
       TRIVY_MED=$(jq  '[.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")]  | length' .appsec-results/trivy-results.json 2>/dev/null) && \
       TRIVY_LOW=$(jq  '[.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")]     | length' .appsec-results/trivy-results.json 2>/dev/null); then
    printf "%-22s %-10s %-6s %-8s %-5s\n" "Trivy" "$TRIVY_CRIT" "$TRIVY_HIGH" "$TRIVY_MED" "$TRIVY_LOW"
    TOTAL_CRITICAL=$((TOTAL_CRITICAL + TRIVY_CRIT)); TOTAL_HIGH=$((TOTAL_HIGH + TRIVY_HIGH))
  else
    print_unknown_report "Trivy"
  fi
elif $RUN_TRIVY; then
  print_missing_report "Trivy"
fi

echo "============================================================"
printf "%-22s %-10s %-6s\n" "TOTAL C+H" "$TOTAL_CRITICAL" "$TOTAL_HIGH"
echo "============================================================"

echo ""
if $HAS_SUMMARY_UNKNOWN; then
  echo "WARNING: One or more scanner summaries are UNKNOWN."
  echo "  Review .appsec-results/ and the warnings above before pushing."
  echo "  This scan does not block your commit — you are responsible for acting on findings."
elif [ "$TOTAL_CRITICAL" -gt 0 ] || [ "$TOTAL_HIGH" -gt 0 ]; then
  echo "WARNING: $TOTAL_CRITICAL Critical and $TOTAL_HIGH High findings detected."
  echo "  Review .appsec-results/ and address these before pushing."
  echo "  This scan does not block your commit — you are responsible for acting on findings."
else
  echo "All clear — no Critical or High findings."
fi
echo ""
echo "Tip: Run /appsec-scan before every commit or push to catch issues early."
```

---

## Step 6 — Findings review and fix loop

When any scanner reports findings, walk this loop. It generalizes remediation
across all categories (secrets, SAST, container, and legacy scanners).

### 6.1 Classify every finding

Present the user a table of all findings and classify each as:

- **Solvable now** — a local code/config/dependency change fixes it: a committed
  secret to externalize, a dependency with a known fixed version to upgrade, a
  code-level SAST finding with a clear safe rewrite, a base-image bump for a
  container CVE with a patched tag.
- **Not fixable here** — goes to the triage plan (Step 7): no fixed version
  exists, apparent false positive, finding is in test-only code, requires an
  architectural change, lives in vendored/third-party code, or the scanner is
  CI-only (e.g. dependency findings matched server-side after push).

For secret findings, show only the redacted summary — never print raw secret
values, even if they are present in the JSON artifact.

### 6.2 Ask for approval once before making changes

The approval request must name the new branch that will be created —
`appsec/fix-<YYYYMMDD>-<shortsha>` — list which findings will be attempted, and
state that the loop continues until those findings are clean or the iteration
cap is reached. One approval covers the whole loop; do not re-ask each
iteration.

### 6.3 After approval: create a new branch and loop

```
git checkout -b appsec/fix-<YYYYMMDD>-<shortsha>
```

Then loop, for a **maximum of 5 iterations**:

1. Apply fixes for the solvable findings (match the app's existing configuration
   patterns; for secrets use environment variables, CI/CD variables,
   `.env.example` placeholders, or a secret manager lookup).
2. Rerun **only the affected scanners**, not the full suite. For secret
   findings, Rerun only GitLab Secret Detection first; for SAST fixes rerun only
   GitLab SAST (or Fortify); for container fixes rerun only Container Scanning.
3. Reclassify what remains. Findings that stopped appearing are done; findings
   that survived a genuine fix attempt twice get reclassified as *not fixable
   here* with a note.
4. **Abort early if an iteration makes no progress** (no finding count went
   down) — do not burn the remaining iterations.

When the loop ends (clean, cap hit, or no-progress abort),
run the app's relevant tests before reporting back. Use the repo's documented test command
when present; otherwise infer the narrowest meaningful test command from the
project manifests. Commit the fixes on the fix branch with a message listing
which findings each change addresses.

### 6.4 Guardrails (non-negotiable)

- **Never rewrite git history** — no rebase, no amend of pushed commits, no
  force-push, no history-scrubbing tools. If a leaked secret warrants history
  cleanup, say so in the report and let the user drive that separately.
- **Never push or open an MR without the user explicitly asking.** When the
  loop finishes, offer: push the branch and open an MR (`git push -u origin
  <branch>` + `glab mr create`) — and wait for the answer.
- Maximum 5 fix iterations; one user approval for the whole loop; stop and ask
  if a fix would delete user data, change production credentials, or pick
  between product behaviors.

---

## Step 7 — Generate the triage plan (TRIAGE.md)

After the loop, write `.appsec-results/TRIAGE.md` covering every finding that
was **not** fixed. This is the user's guided companion for GitLab's
Vulnerability Report triage after they push.

Structure the file exactly like this:

```markdown
# AppSec Triage Plan — <APP_NAME> @ <shortsha> (<date>, profile: <profile>)

## How these findings reach GitLab
Security scan results populate the project Vulnerability Report when the
scanners run in a pipeline on the **default branch** (GitLab Ultimate).
MR pipelines show new findings in the MR security widget first. Dependency
Scanning findings are matched from the uploaded SBOM server-side.

## How to dismiss a finding (UI)
Secure → Vulnerability report → open the finding → **Dismiss vulnerability**
→ pick the dismissal reason below → paste the justification comment (a comment
is mandatory).

## Findings

### <n>. [<severity>] <title> — <scanner>
- Location: <file:line or image:layer>
- Why not fixed here: <reason>
- Dismissal reason: `<one of the five below>`
- Justification (paste-ready): "<2-3 sentences: what was assessed, why this
  reason applies, compensating controls if any, review-by date if temporary>"
```

Use exactly one of GitLab's five dismissal reasons per finding (these are the
only values GitLab accepts):

| Reason | Use when |
|---|---|
| `false_positive` | The scanner is wrong — the flagged pattern is not exploitable |
| `used_in_tests` | The finding lives in test code/fixtures, never in production |
| `acceptable_risk` | Real but consciously accepted — name the owner + review date |
| `mitigating_control` | A compensating control (WAF, network policy, authz layer) neutralizes it |
| `not_applicable` | The affected code path is unused/unreachable/being decommissioned |

Findings you expect to be fixed by the branch (once merged) do not belong in
TRIAGE.md — they resolve automatically in the next default-branch pipeline.

---

## DAST (web + API) — CI-referenced

DAST needs a **running, deployed target**, so it cannot run in this pre-push
loop; it belongs in the pipeline against a review/staging environment. What
this skill does for the `dast_web` / `dast_api` categories:

1. Resolve the DAST component from the catalog (Step 2.5) and show its guide.
2. Gather the inputs a CI DAST job needs — look in the repo for an OpenAPI spec
   (`openapi.*`, `swagger.*`) or a Postman collection (`*.postman_collection.json`);
   if none found, ask the user for the target URL (web) and/or API spec (api).
3. Emit a ready-to-paste snippet for `.gitlab-ci.yml`:

```yaml
include:
  - component: <gitlab_instance_host>/components/dast/dast@<resolved-version>
# DAST_WEBSITE / DAST_API_SPECIFICATION etc. per the component README
```

For local, design-time DAST-style coverage (no running app required), point the
user at the **appsec-dast-sim** skill from this same plugin.

---

## What NOT to do

- Do not edit scanner commands directly in this file — edit `scanners/*.sh` instead
- Do not add `fortifyclient` upload steps — scan-only is the local model
- Do not remove `--network=host` from Scantist — it needs to reach the DTP server
- Do not run Scantist Maven before Parasoft Maven — it needs compiled artifacts
- Do not print raw secret values from `gl-secret-detection-report.json`
- Do not treat removing a detected value from source as credential rotation
- Do not commit `.appsec-results/` to git
- Do not contact any network endpoint other than the active profile's
  `gitlab_instance` (catalog metadata) and the configured image registries
- Do not rewrite git history, and do not push or open MRs without the user
  explicitly asking
- Do not exceed 5 fix-loop iterations or continue after a no-progress iteration

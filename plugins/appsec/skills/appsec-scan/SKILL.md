---
name: appsec-scan
description: >
  Run the same security scanners as CI — locally, using identical container images —
  before pushing to GitLab, driven by admin-managed scanner preferences and the
  private GitLab CI/CD Catalog at lobster-thermidor/devops/ci-catalogue with
  per-component version pinning (~latest or exact tag). Categories:
  SAST (Fortify SCA, multi-language: maven, gradle, python, javascript),
  Dependency Scanning (GitLab SBOM), Secret Detection (GitLab/Gitleaks),
  Container Scanning (GTCS).
  Reports findings, then (with approval) creates a fix branch, loops fix→rescan,
  and generates a guided triage plan (.appsec-results/TRIAGE.md) for findings it
  cannot fix, mapped to the GitLab Vulnerability Report dismissal workflow.
  Use when the user says: "appsec scan", "run security scanners", "run Fortify",
  "pre-push security check", "CI security pipeline locally", "mirror CI scanners",
  "container security scan", "SCA scan", "SAST scan", "dependency scan",
  "secret scan", "secret detection", "security before merge", "scan profile",
  "catalog components", "triage plan", "fix security findings".
  Do NOT activate for general code review, unit testing, or lint-only requests.
---

# AppSec Scan — Catalog-Driven CI Mirror

Run the same scanner images your GitLab CI pipeline uses, locally, so you catch
findings before the push. Which scanner runs for each category is decided by
admin-managed preferences, and component versions are resolved from the private
GitLab CI/CD Catalog (`lobster-thermidor/devops/ci-catalogue`) on every run.

## How this skill is structured

```
skills/appsec-scan/
├── SKILL.md                  ← you are here — orchestration only
├── UPDATE-GUIDE.md           ← maintainer guide (component changes, snapshots)
├── config/
│   ├── scanner-preferences.yaml  ← admin-owned category→scanner profiles
│   └── PREFERENCES.md            ← schema + switching guide
├── scripts/
│   ├── load-prefs.sh         ← YAML → shell env/RUN_* flags (the model never parses YAML)
│   ├── catalog.sh            ← CI/CD Catalog resolver (tags, template, README, AGENTS.md, drift)
│   ├── detect-runtime.sh     ← picks docker or podman
│   ├── resolve-jq.sh         ← host jq, or fetch from settings.jq.install_url
│   └── container-target.sh   ← builds/saves a local image, or resolves CS_IMAGE
├── scanners/                 ← one runner per scanner; each mirrors one CI component
│   ├── fortify-sast.sh
│   ├── gitlab-dependency-scanning.sh
│   ├── gitlab-container-scanning.sh
│   ├── secret-detection.sh
│   └── preflight.sh
└── reference/
    └── catalog/              ← vendored component snapshots (offline fallback)
        └── lobster-thermidor/devops/ci-catalogue/
            ├── fortify-sast/fortify-sast/25.2.0/
            ├── dependency-scanning/dependency-scanning/1.0.0/
            ├── secret-detection/secret-detection/1.0.0/
            └── container-scanning/container-scanning/1.0.0/
```

**To change which scanner runs for a category:** admins edit
`config/scanner-preferences.yaml` (see `config/PREFERENCES.md`).
**To update a scanner's commands:** edit the file in `scanners/`. Do not edit SKILL.md.
**To update a component version or pin an exact tag:** edit `version:` in the
relevant category block in `config/scanner-preferences.yaml`. See UPDATE-GUIDE.md.

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
| `FORTIFY_SAST_IMAGE` | Fortify SCA image (full ref, e.g. `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sca:25.2.0-jdk17-review`) | profile `image:` (env override wins) |
| `FORTIFY_LANGUAGE` | Fortify scan language (`maven`, `gradle`, `python`, `javascript`); auto-detected from project files, set to override | auto-detected |
| `SECRET_DETECTION_IMAGE` | GitLab Secret Detection analyzer image (full ref) | profile `image:` (env override wins) |
| `SECRET_DETECTION_EXCLUDED_PATHS` | Paths excluded by the analyzer | — |
| `GITLAB_DS_IMAGE` | GitLab Dependency Scanning analyzer image (full ref) | profile `image:` (env override wins) |
| `GITLAB_CS_IMAGE` | GitLab Container Scanning analyzer image (full ref) | profile `image:` (env override wins) |
| `CS_IMAGE` | Container image:tag for Container Scanning to scan | — |
| `JFROG_TOKEN` | CI-side variable of the container-scanning component; local runs authenticate via the env vars named in `settings.container_registry` (`CS_REGISTRY_USER`/`CS_REGISTRY_PASSWORD`) | — |
| `APP_NAME` | Application name used in Fortify build IDs | `basename $PWD` |
| `SOURCE_PATH` | Source directory passed to Fortify | `src` |
| `MAVEN_SETTINGS` | Maven settings.xml path (Fortify Maven builds) | `settings.xml` |
| `CI_PROJECT_URL` | GitLab project URL (Fortify source control config) | — |

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

## Step 1.5 — Load scanner preferences and detect runtime

Run `scripts/load-prefs.sh` — it parses `config/scanner-preferences.yaml` and
prints ready-to-eval shell assignments. Do not parse the YAML yourself and do
not infer endpoints or images: everything the run needs is emitted by the
script, and the runner→`RUN_*` flag mapping table lives in its header comment.

```bash
PREFS_ENV="$(bash "$SCRIPTS_DIR/load-prefs.sh" "$SKILL_DIR/config/scanner-preferences.yaml")" || {
  echo "ERROR: failed to load scanner preferences — see the message above."
  echo "Fix config/scanner-preferences.yaml (or unset APPSEC_PROFILE) and re-run."
  return 1
}
eval "$PREFS_ENV"
# Now set: APPSEC_PROFILE, APPSEC_AIRGAP, CONTAINER_RUNTIME, JQ_INSTALL_URL,
# CATALOG_MODE, CATALOG_AUTH_ENV, CS_USER_ENV, CS_PASS_ENV, GITLAB_INSTANCE,
# FORTIFY_SAST_IMAGE, SECRET_DETECTION_IMAGE, GITLAB_DS_IMAGE, GITLAB_CS_IMAGE,
# RUN_FORTIFY_SAST, RUN_GITLAB_DS, RUN_SECRET_DETECTION, RUN_GITLAB_CS,
# and ENABLED_COMPONENTS (space-separated "component|version|runner" triples).

# Detect the container runtime (docker or podman) — hard requirement.
RUNTIME="$(CONTAINER_RUNTIME="$CONTAINER_RUNTIME" bash "$SCRIPTS_DIR/detect-runtime.sh")" || {
  echo "ERROR: no container runtime (docker or podman) found"; return 1; }

echo "Profile: $APPSEC_PROFILE   GitLab: $GITLAB_INSTANCE   Runtime: $RUNTIME   Airgap: $APPSEC_AIRGAP"
```

- The emitted `*_IMAGE` values are what actually run (pinned by the admin);
  Step 2.5 resolves `component:` only for its usage guide and a drift advisory.
  An explicit `*_IMAGE` env var set before the run still wins over the YAML.
- If load-prefs.sh exits nonzero (unknown profile, or `airgap: true` with a
  profile whose `gitlab_instance` contains gitlab.com), show its stderr to the
  user verbatim and stop.
- If `GITLAB_INSTANCE` still points at a `*.example` host or the images still
  point at `jfrog.internal/...`, the admin has not configured this profile yet —
  stop and direct the user to the repo README section "AppSec airgap setup".

---

## Step 2 — Preflight: validate required environment

Runs `scanners/preflight.sh` in its own process — a real shell script that is
shellchecked and can be run standalone.

```bash
CATALOG_AUTH_ENV="$CATALOG_AUTH_ENV" APPSEC_AIRGAP="$APPSEC_AIRGAP" \
  APPSEC_PROFILE="$APPSEC_PROFILE" CONTAINER_RUNTIME="$CONTAINER_RUNTIME" \
  bash "$SCANNERS_DIR/preflight.sh" || return 1
```

If preflight fails, show its output to the user and stop — its error lines name
exactly which variables to set. Never start scanners against an incomplete
environment.

---

## Step 2.5 — Resolve CI/CD Catalog components (every run)

For every **enabled** category component in the active profile, resolve the
component against the catalog and check drift. `scripts/catalog.sh` is the only
thing that talks to the network, and only to `$GITLAB_INSTANCE`. When
`CATALOG_MODE=offline` (or the fetch fails) it uses the vendored snapshots in
`reference/catalog/` and says so — the scan still runs.

```bash
CATALOG_CACHE=".appsec-results/catalog"
mkdir -p "$CATALOG_CACHE"

# ENABLED_COMPONENTS comes from Step 1.5: space-separated "component|version|runner" triples.
for pair in $ENABLED_COMPONENTS; do
  component="${pair%%|*}"; rest="${pair#*|}"; version="${rest%%|*}"; runner="${rest#*|}"
  bash "$SCRIPTS_DIR/catalog.sh" resolve "$GITLAB_INSTANCE" "$component" "$version" "$CATALOG_CACHE" "$CATALOG_AUTH_ENV"
  if [ "$runner" != "none" ]; then
    bash "$SCRIPTS_DIR/catalog.sh" check-drift "$component" "$CATALOG_CACHE" "$SCANNERS_DIR/$runner"
  fi
done
```

If `CATALOG_MODE=offline`, skip the `resolve` network call and read straight
from `reference/catalog/`. If `resolve` reports an authentication failure
(HTTP 401/403), tell the user: anonymous catalog reads are disabled on this
instance — create a `read_api` Personal Access Token, put it in an env var, and
set `settings.catalog.auth_token_env` to that var's name; meanwhile the run
continues on the vendored snapshot.

Then present the user a resolution table before scanning:

| Category | Component | Version | Source | Drift |
|---|---|---|---|---|
| sast | lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast | 25.2.0 | online | — |

- `resolve` accepts an exact tag (e.g. `25.2.0`) or `~latest` (resolves to the
  highest stable release each run). Prints `<component>@<tag> [online|offline-fallback]`
  and logs which tags were considered and why one was chosen.
- When an exact version is pinned and a newer stable tag exists, `resolve` prints:
  `ADVISORY: <component> pinned <X>, newer stable <Y> available` — surface this
  to the user verbatim so admins know when to bump the pin.
- `check-drift` prints `DRIFT:` lines when the component's defaults have moved
  ahead of the local runner — surface these to the user verbatim.
- `catalog.sh` also caches `AGENTS.md` per component (alongside `template.yml`
  and `README.md`) — the AGENTS.md is the component's agent-oriented usage
  reference (offer to summarize it if the user wants component details).
- The resolved `template.yml` and `README.md` are **advisory only**: `DRIFT:`
  lines tell the admin when to bump the pinned `image:` in the preferences.
  Never derive the Step 4 analyzer images from the catalog — they were fixed in
  Step 1.5.

---

## Step 3 — Detect project type and set defaults

```bash
APP_NAME="${APP_NAME:-$(basename "$PWD")}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SOURCE_PATH="${SOURCE_PATH:-src}"
CI_PROJECT_DIR="${CI_PROJECT_DIR:-$PWD}"
APPSEC_REGISTRY="${APPSEC_REGISTRY:-registry.company.com/security}"

# Analyzer images (FORTIFY_SAST_IMAGE, SECRET_DETECTION_IMAGE, GITLAB_DS_IMAGE,
# GITLAB_CS_IMAGE) were set from each category's image: in Step 1.5. The Step 2.5
# drift advisory tells you when the catalog moved ahead of a pinned image.

FORTIFY_SAST_PID=""; GITLAB_DS_PID=""; SECRET_DETECTION_PID=""; GITLAB_CS_PID=""

HAS_POM=false; HAS_GRADLE=false; HAS_PACKAGE_JSON=false
HAS_REQUIREMENTS=false; HAS_DOCKERFILE=false
[ -f pom.xml ]                                         && HAS_POM=true
{ [ -f build.gradle ] || [ -f build.gradle.kts ]; }   && HAS_GRADLE=true
[ -f package.json ]                                    && HAS_PACKAGE_JSON=true
{ [ -f requirements.txt ] || [ -f pyproject.toml ]; } && HAS_REQUIREMENTS=true
[ -f Dockerfile ]                                      && HAS_DOCKERFILE=true

# Composite flag used in scanner-preferences.yaml condition: field
HAS_POM_NO_GRADLE=false; { $HAS_POM && ! $HAS_GRADLE; } && HAS_POM_NO_GRADLE=true

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

Run a category block only when its `RUN_*` flag from Step 1.5 is true. Run
the parallel scanners first (background `&`), then the sequential ones.

### Fortify SCA (SAST)
*Category: sast. Multi-language (maven, gradle, python, javascript). Language
auto-detected from project files; set `FORTIFY_LANGUAGE` to override.
Image: `FORTIFY_SAST_IMAGE`. Runner: `scanners/fortify-sast.sh`. Output:
`.appsec-results/fortify-sast.fpr`.*

```bash
if $RUN_FORTIFY_SAST && [ -n "${FORTIFY_SAST_IMAGE:-}" ]; then
  # Auto-detect language (precedence: gradle > maven > python > javascript)
  if [ -z "${FORTIFY_LANGUAGE:-}" ]; then
    if $HAS_GRADLE;       then FORTIFY_LANGUAGE=gradle
    elif $HAS_POM;        then FORTIFY_LANGUAGE=maven
    elif $HAS_REQUIREMENTS; then FORTIFY_LANGUAGE=python
    elif $HAS_PACKAGE_JSON; then FORTIFY_LANGUAGE=javascript
    else
      echo "[Fortify SCA] No supported project type detected (need build.gradle, pom.xml, requirements.txt, or package.json); skipping"
      RUN_FORTIFY_SAST=false
    fi
  fi
  if $RUN_FORTIFY_SAST; then
    echo "[Fortify SCA] Pulling ${FORTIFY_SAST_IMAGE}..."
    if "$RUNTIME" pull "${FORTIFY_SAST_IMAGE}"; then
      echo "[Fortify SCA] Starting in background (language: $FORTIFY_LANGUAGE)..."
      "$RUNTIME" run --rm \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" \
        -w /workspace \
        -e APP_NAME="$APP_NAME" \
        -e SOURCE_PATH="$SOURCE_PATH" \
        -e FORTIFY_LANGUAGE="$FORTIFY_LANGUAGE" \
        -e MAVEN_SETTINGS="${MAVEN_SETTINGS:-}" \
        -e ARTIFACTORY_USER="${ARTIFACTORY_USER:-}" \
        -e ARTIFACTORY_PASSWORD="${ARTIFACTORY_PASSWORD:-}" \
        "${FORTIFY_SAST_IMAGE}" \
        sh /runner.sh > .appsec-results/fortify-sast.log 2>&1 &
      FORTIFY_SAST_PID=$!
    else
      echo "[Fortify SCA] Failed to pull ${FORTIFY_SAST_IMAGE}; skipping scan"
    fi
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
  if "$RUNTIME" pull "${GITLAB_DS_IMAGE}"; then
    echo "[GitLab DS] Starting in background..."
    "$RUNTIME" run --rm \
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
  if "$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"; then
    echo "[Secret Detection] Starting in background..."
    "$RUNTIME" run --rm \
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

### Wait for all parallel scanners

```bash
echo "Waiting for parallel scanners..."
for pid_var in FORTIFY_SAST_PID GITLAB_DS_PID SECRET_DETECTION_PID; do
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

### GitLab Container Scanning (GTCS)
*Category: container_scanning. Runner: `scanners/gitlab-container-scanning.sh`.
Sequential (it builds/saves an image). GTCS is **registry-only**, so the target
is resolved by `scripts/container-target.sh`: a registry image named by
`CS_IMAGE` runs the real `gtcs scan`; otherwise a local `Dockerfile` is built,
saved to a tarball, and scanned with the analyzer image's bundled Trivy — fully
offline, no registry, no socket.*

```bash
if $RUN_GITLAB_CS && [ -n "${GITLAB_CS_IMAGE:-}" ]; then
  # Resolve the scan target on the host (build+save a local Dockerfile, or use CS_IMAGE).
  CS_TARGET="$(bash "$SCRIPTS_DIR/container-target.sh" "$RUNTIME" "$APP_NAME" ".appsec-results" || true)"
  CS_MODE="${CS_TARGET%%|*}"; CS_VALUE="${CS_TARGET#*|}"
  case "$CS_MODE" in
    registry)
      echo "[GitLab CS] Scanning registry image $CS_VALUE..."
      "$RUNTIME" pull "${GITLAB_CS_IMAGE}" && \
      "$RUNTIME" run --rm --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
        -w /workspace \
        -e CI_PROJECT_DIR="/workspace" \
        -e CS_SCAN_MODE="registry" \
        -e CS_IMAGE="$CS_VALUE" \
        -e CS_REGISTRY_USER="$(printenv "$CS_USER_ENV" 2>/dev/null || true)" \
        -e CS_REGISTRY_PASSWORD="$(printenv "$CS_PASS_ENV" 2>/dev/null || true)" \
        "${GITLAB_CS_IMAGE}" \
        sh /runner.sh 2>&1 | tee .appsec-results/gitlab-cs.log
      GITLAB_CS_PID="ran"   # sequential; mark that CS produced output
      ;;
    archive)
      echo "[GitLab CS] Scanning locally-built image (offline, bundled Trivy)..."
      "$RUNTIME" pull "${GITLAB_CS_IMAGE}" && \
      "$RUNTIME" run --rm --entrypoint "" \
        -v "$PWD:/workspace" \
        -v "$SCANNERS_DIR/gitlab-container-scanning.sh:/runner.sh:ro" \
        -w /workspace \
        -e CI_PROJECT_DIR="/workspace" \
        -e CS_SCAN_MODE="archive" \
        -e CS_ARCHIVE="/workspace/.appsec-results/container-image.tar" \
        "${GITLAB_CS_IMAGE}" \
        sh /runner.sh 2>&1 | tee .appsec-results/gitlab-cs.log
      GITLAB_CS_PID="ran"
      ;;
    error)
      echo "[GitLab CS] Could not prepare a scan target (see container-target.sh output above)."
      ;;
    *)
      echo "[GitLab CS] Deferred to CI — no CS_IMAGE and no Dockerfile found."
      echo "  Container scanning runs post-build in the pipeline."
      ;;
  esac
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
HAS_MISSING_REPORT=false

HAS_JQ=true
HAS_UNZIP=true
# Resolve jq: use host jq, else fetch from settings.jq.install_url (Step 1.5).
JQ_BIN="$(JQ_INSTALL_URL="${JQ_INSTALL_URL:-}" APPSEC_RESULTS_DIR=".appsec-results" bash "$SCRIPTS_DIR/resolve-jq.sh" || true)"
if [ -n "$JQ_BIN" ]; then PATH="$(dirname "$JQ_BIN"):$PATH"; else HAS_JQ=false; fi
command -v unzip >/dev/null 2>&1 || HAS_UNZIP=false

if ! $HAS_JQ || ! $HAS_UNZIP; then
  echo "WARNING: One or more summary parsers are unavailable; some counts may show as UNKNOWN."
  ! $HAS_JQ && echo "  - jq not found: Secret Detection, GitLab DS/CS counts may be unavailable."
  ! $HAS_UNZIP && echo "  - unzip not found: Fortify FPR counts may be unavailable."
fi

print_missing_report() {
  printf "%-22s %s\n" "$1" "WARNING: report file not present"
  # A scanner that was selected to run but produced no report means we do NOT
  # know its result — never let the run end with a false "All clear".
  HAS_MISSING_REPORT=true
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

# Fortify SCA — count <Vulnerability> tags in the embedded fvdl
if $RUN_FORTIFY_SAST; then
  fpr_file=".appsec-results/fortify-sast.fpr"
  if [ -f "$fpr_file" ]; then
    if ! $HAS_UNZIP; then
      print_unknown_report "Fortify SCA (SAST)"
    elif unzip -p "$fpr_file" audit.fvdl >/dev/null 2>&1; then
      count=$(unzip -p "$fpr_file" audit.fvdl 2>/dev/null | grep -c '<Vulnerability>' || true)
      printf "%-22s %-10s\n" "Fortify SCA (SAST)" "$count total (see .fpr for severity breakdown)"
    else
      print_unknown_report "Fortify SCA (SAST)"
    fi
  else
    print_missing_report "Fortify SCA (SAST)"
  fi
fi

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

# GitLab Container Scanning — registry mode emits GitLab schema; archive mode
# (local build) emits trivy-native schema. Parse whichever exists.
if [ -n "$GITLAB_CS_PID" ]; then
  if [ -f .appsec-results/gl-container-scanning-report.json ]; then
    print_gl_report "GitLab CS" .appsec-results/gl-container-scanning-report.json true
  elif [ -f .appsec-results/container-scan-archive.json ]; then
    if ! $HAS_JQ; then
      print_unknown_report "GitLab CS"
    elif CS_CRIT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' .appsec-results/container-scan-archive.json 2>/dev/null) && \
         CS_HIGH=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")]     | length' .appsec-results/container-scan-archive.json 2>/dev/null) && \
         CS_MED=$(jq  '[.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")]   | length' .appsec-results/container-scan-archive.json 2>/dev/null) && \
         CS_LOW=$(jq  '[.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")]      | length' .appsec-results/container-scan-archive.json 2>/dev/null); then
      printf "%-22s %-10s %-6s %-8s %-5s\n" "GitLab CS (local)" "$CS_CRIT" "$CS_HIGH" "$CS_MED" "$CS_LOW"
      TOTAL_CRITICAL=$((TOTAL_CRITICAL + CS_CRIT)); TOTAL_HIGH=$((TOTAL_HIGH + CS_HIGH))
    else
      print_unknown_report "GitLab CS"
    fi
  else
    print_missing_report "GitLab CS"
  fi
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

echo "============================================================"
printf "%-22s %-10s %-6s\n" "TOTAL C+H" "$TOTAL_CRITICAL" "$TOTAL_HIGH"
echo "============================================================"

echo ""
if $HAS_MISSING_REPORT; then
  echo "WARNING: One or more selected scanners produced NO report (image pull or"
  echo "  run failed). Results are incomplete — this is NOT an all-clear. Check the"
  echo "  per-scanner logs in .appsec-results/ (e.g. failed docker/podman pulls)."
  echo "  This scan does not block your commit — you are responsible for acting on findings."
elif $HAS_SUMMARY_UNKNOWN; then
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
across all categories (secrets, SAST, container, dependency).

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
   findings, rerun only GitLab Secret Detection first; for SAST fixes rerun only
   Fortify SCA; for container fixes rerun only Container Scanning.
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

## DAST (web + API)

For local, design-time DAST-style coverage (no running app required), use the
**appsec-dast-sim** skill from this same plugin.

---

## What NOT to do

- Do not edit scanner commands directly in this file — edit `scanners/*.sh` instead
- Do not add `fortifyclient` upload steps — scan-only is the local model
- Do not print raw secret values from `gl-secret-detection-report.json`
- Do not treat removing a detected value from source as credential rotation
- Do not commit `.appsec-results/` to git
- Do not contact any network endpoint other than the active profile's
  `gitlab_instance` (catalog metadata) and the configured image registries
- Do not rewrite git history, and do not push or open MRs without the user
  explicitly asking
- Do not exceed 5 fix-loop iterations or continue after a no-progress iteration

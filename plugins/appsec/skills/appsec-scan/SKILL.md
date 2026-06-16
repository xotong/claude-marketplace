---
name: appsec-scan
description: >
  Run the same security scanners as CI — locally, using identical container images —
  before pushing to GitLab. Covers Fortify SAST (Python and JS), Parasoft Jtest
  (Gradle and Maven), Pylint (SARIF output), ESLint (JSON output), Scantist SCA
  (JAR-based dependency analysis), and Trivy (container image scanning).
  Results go to .appsec-results/ and a severity-gated summary is printed at the end.
  Use when the user says: "appsec scan", "run security scanners", "run Fortify",
  "run Parasoft", "Scantist scan", "Trivy scan", "ESLint security", "Pylint scan",
  "pre-push security check", "CI security pipeline locally", "mirror CI scanners",
  "container security scan", "SCA scan", "SAST scan", "security before merge".
  Do NOT activate for general code review, unit testing, or lint-only requests.
---

# AppSec Scan — CI Mirror

Run the same scanner images your GitLab CI pipeline uses, locally, so you catch
findings before the push.

## How this skill is structured

Scanner commands live in `scanners/` — one shell script per scanner-language
combination. Each script mirrors one GitLab CI component exactly.

```
skills/appsec-scan/
├── SKILL.md              ← you are here — orchestration only, rarely changes
├── UPDATE-GUIDE.md       ← how to update when a CI component changes
└── scanners/
    ├── fortify-python.sh ← mirrors fortify-scan-python3 CI component
    ├── fortify-js.sh     ← mirrors fortify-scan-js CI component
    ├── parasoft-gradle.sh
    ├── parasoft-maven.sh
    ├── pylint.sh
    ├── eslint.sh
    ├── scantist-js.sh
    ├── scantist-maven.sh
    └── trivy.sh
```

**To update a scanner:** edit the file in `scanners/`. Do not edit SKILL.md.
**To add a language variant:** add a new file in `scanners/`, then add one
detection block in Step 3 below. See UPDATE-GUIDE.md for full instructions.

---

## Prerequisites

Tenants must configure `npm`/`pip` and container image pulls to their internal
JFrog virtual repos. Network access to JFrog is required.

| Variable | Description | Default |
|---|---|---|
| `APPSEC_REGISTRY` | Registry prefix for all scanner images | `registry.company.com/security` |
| `FORTIFY_PY_IMAGE` | Fortify image for Python (e.g. `fortify-sast:latest-jdk17`) | — |
| `FORTIFY_JS_IMAGE` | Fortify image for JS/TS | — |
| `PARASOFT_IMAGE` | Parasoft Jtest image (shared for Gradle and Maven) | — |
| `PYLINT_IMAGE` | Pylint image (with pylint + pylint2sarif installed) | — |
| `ESLINT_IMAGE` | ESLint image (with npm/npx) | — |
| `SCANTIST_IMAGE` | Scantist image (with Java + curl + sudo) | — |
| `TRIVY_IMAGE` | Trivy image | — |
| `DEVSECOPS_IMPORT_URL` | DTP server URL for Scantist JAR download | — |
| `APP_NAME` | Application name used in Fortify build IDs | `basename $PWD` |
| `SOURCE_PATH` | Source directory passed to Fortify and Pylint | `src` |
| `ESLINT_CONFIG_FILE` | Path to ESLint config file | — |
| `MAVEN_SETTINGS_XML` | Maven settings.xml (Parasoft Maven + Scantist Maven) | — |
| `TRIVY_TARGET` | Container image:tag to scan with Trivy | — |
| `CI_PROJECT_URL` | GitLab project URL (Parasoft source control config) | — |

Set these in your shell profile (`~/.bashrc` or `~/.zshrc`):

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

## Step 1 — Locate the skill's scanner directory

The scanner scripts are relative to the skill's own directory, not the project
being scanned. Resolve this path first — subsequent steps depend on `SCANNERS_DIR`.

```bash
# SKILL_DIR is the absolute path to skills/appsec-scan/
# Adjust this path if your plugin is installed at a different location.
SKILL_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
SCANNERS_DIR="$SKILL_DIR/scanners"

if [ ! -d "$SCANNERS_DIR" ]; then
  echo "ERROR: scanners/ directory not found at $SCANNERS_DIR"
  echo "Ensure the full appsec-scan skill directory is present, not just SKILL.md"
  exit 1
fi
```

---

## Step 2 — Preflight: validate required environment

Runs `scanners/preflight.sh` in its own process — a real shell script that is
shellchecked and can be run standalone. Checks that required env vars are set
and exits with a clear message if not.

```bash
bash "$SCANNERS_DIR/preflight.sh" || return 1
```

---

## Step 3 — Detect project type and set defaults

```bash
APP_NAME="${APP_NAME:-$(basename "$PWD")}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SOURCE_PATH="${SOURCE_PATH:-src}"
CI_PROJECT_DIR="${CI_PROJECT_DIR:-$PWD}"
APPSEC_REGISTRY="${APPSEC_REGISTRY:-registry.company.com/security}"
FORTIFY_PY_PID=""; FORTIFY_JS_PID=""; PYLINT_PID=""; ESLINT_PID=""; SCANTIST_JS_PID=""

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
The container executes `bash /runner.sh`. All output paths inside the script
use `/workspace/...` which maps to `$PWD` on the host.

Run the parallel scanners first (background `&`), then the sequential ones.

### Fortify SAST — Python
*Applies when: Python project detected. Runner: `scanners/fortify-python.sh`.*

```bash
if $HAS_REQUIREMENTS && [ -n "${FORTIFY_PY_IMAGE:-}" ]; then
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
*Applies when: JS/TS project detected. Runner: `scanners/fortify-js.sh`.*

```bash
if $HAS_PACKAGE_JSON && [ -n "${FORTIFY_JS_IMAGE:-}" ]; then
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

### Pylint
*Applies when: Python project. Entrypoint overridden to `""`. Runner: `scanners/pylint.sh`.*

```bash
if $HAS_REQUIREMENTS && [ -n "${PYLINT_IMAGE:-}" ]; then
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
*Applies when: JS/TS project and `ESLINT_CONFIG_FILE` is set. Runner: `scanners/eslint.sh`.*

```bash
if $HAS_PACKAGE_JSON && [ -n "${ESLINT_IMAGE:-}" ] && [ -n "${ESLINT_CONFIG_FILE:-}" ]; then
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
*Applies when: JS/TS project. Needs `--network=host` to reach DTP. Runner: `scanners/scantist-js.sh`.*

```bash
if $HAS_PACKAGE_JSON && [ -n "${SCANTIST_IMAGE:-}" ] && [ -n "${DEVSECOPS_IMPORT_URL:-}" ]; then
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
for pid_var in FORTIFY_PY_PID FORTIFY_JS_PID PYLINT_PID ESLINT_PID SCANTIST_JS_PID; do
  pid="${!pid_var:-}"
  if [ -n "$pid" ]; then
    if wait "$pid"; then
      echo "[${pid_var/_PID/}] Done"
    else
      echo "[${pid_var/_PID/}] Failed — check .appsec-results/ for logs"
    fi
  fi
done
```

### Parasoft Jtest — Gradle
*Sequential. Applies when: Gradle project. Runner: `scanners/parasoft-gradle.sh`.*

```bash
if $HAS_GRADLE && [ -n "${PARASOFT_IMAGE:-}" ]; then
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
*Sequential. Applies when: Maven project (no Gradle). Runner: `scanners/parasoft-maven.sh`.*

```bash
if $HAS_POM && ! $HAS_GRADLE && [ -n "${PARASOFT_IMAGE:-}" ] && [ -n "${MAVEN_SETTINGS_XML:-}" ]; then
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
*Sequential — runs after Parasoft Maven (needs compiled artifacts). Runner: `scanners/scantist-maven.sh`.*

```bash
if $HAS_POM && ! $HAS_GRADLE && [ -n "${SCANTIST_IMAGE:-}" ] && [ -n "${DEVSECOPS_IMPORT_URL:-}" ] && [ -n "${MAVEN_SETTINGS_XML:-}" ]; then
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
*Run if `TRIVY_TARGET` is set. Runner: `scanners/trivy.sh`.*

```bash
if [ -n "${TRIVY_TARGET:-}" ] && [ -n "${TRIVY_IMAGE:-}" ]; then
  echo "[Trivy] Scanning ${TRIVY_TARGET:-}..."
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PWD:/workspace" \
    -v "$SCANNERS_DIR/trivy.sh:/runner.sh:ro" \
    -e TRIVY_TARGET="${TRIVY_TARGET:-}" \
    "${APPSEC_REGISTRY}/${TRIVY_IMAGE:-}" \
    bash /runner.sh
else
  echo "[Trivy] Skipped — set TRIVY_TARGET=<image:tag> to enable"
fi
```

---

## Step 5 — Parse results and severity gate

```bash
echo ""
echo "============================================================"
echo "  AppSec Scan Summary"
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
  ! $HAS_JQ && echo "  - jq not found: Pylint, ESLint, and Trivy counts may be unavailable."
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
else
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
else
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
else
  print_missing_report "Parasoft"
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
else
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

## What NOT to do

- Do not edit scanner commands directly in this file — edit `scanners/*.sh` instead
- Do not add `fortifyclient` upload steps — scan-only is the local model
- Do not remove `--network=host` from Scantist — it needs to reach the DTP server
- Do not run Scantist Maven before Parasoft Maven — it needs compiled artifacts
- Do not commit `.appsec-results/` to git

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

# AppSec Scan — CI-Mirror

Run the same scanner images your GitLab CI pipeline uses, locally, so you catch
findings before the push. Each scanner runs in its own container with the same
image tag CI uses. Results land in `.appsec-results/` and a final gate blocks if
any CRITICAL or HIGH findings are present.

---

## Prerequisites

Collect these values before starting. Ask the user for any that are missing.

| Variable | Description | Default |
|---|---|---|
| `APPSEC_REGISTRY` | Registry prefix for all scanner images | `registry.company.com/security` |
| `FORTIFY_PY_IMAGE` | Fortify image for Python scans (e.g. `fortify-sast:latest-jdk17`) | — |
| `FORTIFY_JS_IMAGE` | Fortify image for JS/TS scans | — |
| `PARASOFT_IMAGE` | Parasoft Jtest image (shared for Gradle and Maven) | — |
| `PYLINT_IMAGE` | Pylint image (with pylint + pylint2sarif installed) | — |
| `ESLINT_IMAGE` | ESLint image (with npm/npx) | — |
| `SCANTIST_IMAGE` | Scantist image (with Java + curl + sudo) | — |
| `TRIVY_IMAGE` | Trivy image (e.g. `trivy:latest`) | — |
| `DEVSECOPS_IMPORT_URL` | DTP server URL for Scantist JAR download and reporting | — |
| `APP_NAME` | Application name used in Fortify build IDs | `basename $PWD` |
| `APP_VERSION` | Application version / branch label | current git branch |
| `SOURCE_PATH` | Source directory to scan (Fortify, Pylint) | `src` |
| `ESLINT_CONFIG_FILE` | Path to ESLint config file | — |
| `MAVEN_SETTINGS_XML` | Maven settings.xml path (Parasoft Maven + Scantist Maven) | — |
| `TRIVY_TARGET` | Container image:tag to scan with Trivy | — |
| `BRANCH` | Branch name (Parasoft + Scantist labels) | current git branch |
| `CI_PROJECT_URL` | GitLab project URL (Parasoft source control config) | — |
| `CI_PROJECT_DIR` | Local workspace root (Parasoft source control config) | `$PWD` |

---

## Step 1 — Detect project type and set defaults

```bash
# Resolve defaults
APP_NAME="${APP_NAME:-$(basename "$PWD")}"
APP_VERSION="${APP_VERSION:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
SOURCE_PATH="${SOURCE_PATH:-src}"
CI_PROJECT_DIR="${CI_PROJECT_DIR:-$PWD}"
APPSEC_REGISTRY="${APPSEC_REGISTRY:-registry.company.com/security}"

# Detect build system
HAS_POM=false; HAS_GRADLE=false; HAS_PACKAGE_JSON=false
HAS_REQUIREMENTS=false; HAS_DOCKERFILE=false
[ -f pom.xml ]          && HAS_POM=true
[ -f build.gradle ] || [ -f build.gradle.kts ] && HAS_GRADLE=true
[ -f package.json ]     && HAS_PACKAGE_JSON=true
[ -f requirements.txt ] || [ -f pyproject.toml ] && HAS_REQUIREMENTS=true
[ -f Dockerfile ]       && HAS_DOCKERFILE=true

echo "Project: $APP_NAME  Branch: $BRANCH"
echo "Detected: POM=$HAS_POM GRADLE=$HAS_GRADLE NPM=$HAS_PACKAGE_JSON PY=$HAS_REQUIREMENTS DOCKER=$HAS_DOCKERFILE"

# Create results directory
mkdir -p .appsec-results
echo "Results will be written to $PWD/.appsec-results"
echo "Add .appsec-results/ to your .gitignore if not already present."
grep -qxF '.appsec-results/' .gitignore 2>/dev/null || echo "  Reminder: .gitignore does not yet exclude .appsec-results/"
```

---

## Step 2 — Fortify SAST (scan only, no SSC upload)

Run Fortify in the background. Pick the correct image for the detected language.
Both Python and JS/TS scans follow the same three-step pattern: clean → translate → scan.

### Fortify Python (run if Python source detected)

```bash
if $HAS_REQUIREMENTS && [ -n "$FORTIFY_PY_IMAGE" ]; then
  echo "[Fortify/Python] Starting scan in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${FORTIFY_PY_IMAGE}" \
    bash -c "
      sourceanalyzer -b ${APP_NAME} -clean
      sourceanalyzer -b ${APP_NAME} -debug-verbose -python-version 3 ${SOURCE_PATH}
      sourceanalyzer -b ${APP_NAME} -scan -f .appsec-results/fortify-python.fpr \
        \$([ -e filter_list.txt ] && echo '-filter filter_list.txt')
    " > .appsec-results/fortify-python.log 2>&1 &
  FORTIFY_PY_PID=$!
  echo "[Fortify/Python] PID $FORTIFY_PY_PID"
fi
```

### Fortify JS/TS (run if package.json detected)

```bash
if $HAS_PACKAGE_JSON && [ -n "$FORTIFY_JS_IMAGE" ]; then
  echo "[Fortify/JS] Starting scan in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${FORTIFY_JS_IMAGE}" \
    bash -c "
      sourceanalyzer -b ${APP_NAME}-js -clean
      sourceanalyzer -b ${APP_NAME}-js -debug-verbose -Dcom.fortify.sca.follow.imports=false ${SOURCE_PATH}
      sourceanalyzer -b ${APP_NAME}-js -scan -f .appsec-results/fortify-js.fpr \
        \$([ -e filter_list.txt ] && echo '-filter filter_list.txt')
    " > .appsec-results/fortify-js.log 2>&1 &
  FORTIFY_JS_PID=$!
  echo "[Fortify/JS] PID $FORTIFY_JS_PID"
fi
```

---

## Step 3 — Pylint (Python linter, SARIF output)

Override the container entrypoint to `""` so the image uses the shell directly.
Runs in parallel with Fortify.

```bash
if $HAS_REQUIREMENTS && [ -n "$PYLINT_IMAGE" ]; then
  echo "[Pylint] Starting scan in background..."
  docker run --rm \
    --entrypoint "" \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${PYLINT_IMAGE}" \
    bash -c "
      cd /workspace
      pylint ${SOURCE_PATH} --exit-zero \
        --output-format=json:.appsec-results/pylint-report.json,text:.appsec-results/pylint-report.txt
      pylint2sarif .appsec-results/pylint-report.json \
        --sarif-output .appsec-results/pylint-report.sarif
      sed -i '1i\\##tool = Pylint' .appsec-results/pylint-report.json
    " > .appsec-results/pylint.log 2>&1 &
  PYLINT_PID=$!
  echo "[Pylint] PID $PYLINT_PID"
fi
```

---

## Step 4 — ESLint (JS/TS linter, JSON output)

```bash
if $HAS_PACKAGE_JSON && [ -n "$ESLINT_IMAGE" ] && [ -n "$ESLINT_CONFIG_FILE" ]; then
  echo "[ESLint] Starting scan in background..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${ESLINT_IMAGE}" \
    bash -c "
      npm install --save-dev --legacy-peer-deps eslint
      npx eslint 'src/**/*.ts' 'src/**/*.tsx' \
        -c ${ESLINT_CONFIG_FILE} \
        --no-eslintrc \
        --ext ts,tsx \
        -f json \
        -o .appsec-results/eslint.json \
        ./
    " > .appsec-results/eslint.log 2>&1 &
  ESLINT_PID=$!
  echo "[ESLint] PID $ESLINT_PID"
fi
```

---

## Step 5 — Wait for parallel scanners (Fortify + Pylint + ESLint)

```bash
echo "Waiting for parallel scanners to complete..."
[ -n "$FORTIFY_PY_PID" ] && wait $FORTIFY_PY_PID && echo "[Fortify/Python] Done" || echo "[Fortify/Python] Failed — check .appsec-results/fortify-python.log"
[ -n "$FORTIFY_JS_PID" ] && wait $FORTIFY_JS_PID && echo "[Fortify/JS] Done"     || echo "[Fortify/JS] Failed — check .appsec-results/fortify-js.log"
[ -n "$PYLINT_PID"     ] && wait $PYLINT_PID     && echo "[Pylint] Done"         || echo "[Pylint] Failed — check .appsec-results/pylint.log"
[ -n "$ESLINT_PID"     ] && wait $ESLINT_PID     && echo "[ESLint] Done"         || echo "[ESLint] Failed — check .appsec-results/eslint.log"
```

---

## Step 6 — Parasoft Jtest

Parasoft requires a DTP server reachable from dev machines. Run synchronously (sequential).

### Parasoft — Gradle project

```bash
if $HAS_GRADLE && [ -n "$PARASOFT_IMAGE" ]; then
  echo "[Parasoft/Gradle] Running..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${PARASOFT_IMAGE}" \
    bash -c "
      echo 'report.format=txt,pdf,xml,html,sast-gitlab,sate' > report.properties
      echo 'report.scontrol=min'                              >> report.properties
      echo 'scontrol.rep.type=git'                            >> report.properties
      echo 'scontrol.rep.git.url=${CI_PROJECT_URL}'           >> report.properties
      echo 'scontrol.branch=${BRANCH}'                        >> report.properties
      echo 'scontrol.rep.git.workspace=${CI_PROJECT_DIR}'     >> report.properties

      ./gradlew clean assemble
      ./gradlew jtest \
        -I \$PARASOFT_INSTALL_DIR/integration/gradle/init.gradle \
        '-Djtest.config=dtp://Recommended-Rules-for-Java' \
        '-Djtest.settings=report.properties' \
        '-Djtest.report=.appsec-results/parasoft-reports' \
        '-Djtest.exclude=path:**/build/**'
    " 2>&1 | tee .appsec-results/parasoft-gradle.log

  # Severity gate: count findings with severity id < 3 (Critical/High)
  PARA_HIGH=0
  if [ -f .appsec-results/parasoft-reports/report.xml ]; then
    PARA_HIGH=$(xmllint --xpath \
      "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id<3])" \
      .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
    echo "[Parasoft/Gradle] Critical/High findings: $PARA_HIGH"
  fi
fi
```

### Parasoft — Maven project

```bash
if $HAS_POM && ! $HAS_GRADLE && [ -n "$PARASOFT_IMAGE" ] && [ -n "$MAVEN_SETTINGS_XML" ]; then
  echo "[Parasoft/Maven] Running..."
  docker run --rm \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${PARASOFT_IMAGE}" \
    bash -c "
      echo 'report.format=pdf,xml,html,sast-gitlab' > report.properties
      echo 'report.scontrol=min'                    >> report.properties
      echo 'scontrol.rep.type=git'                  >> report.properties
      echo 'scontrol.rep.git.url=${CI_PROJECT_URL}' >> report.properties
      echo 'scontrol.branch=${BRANCH}'              >> report.properties
      echo 'scontrol.rep.git.workspace=${CI_PROJECT_DIR}' >> report.properties

      mvn clean install jtest:jtest \
        -s ${MAVEN_SETTINGS_XML} \
        '-DskipTests' \
        '-Djtest.config=dtp://Recommended-Rules-for-Java' \
        '-Djtest.settings=report.properties' \
        '-Djtest.report=.appsec-results/parasoft-reports'
    " 2>&1 | tee .appsec-results/parasoft-maven.log

  PARA_HIGH=0
  if [ -f .appsec-results/parasoft-reports/report.xml ]; then
    PARA_HIGH=$(xmllint --xpath \
      "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id<3])" \
      .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
    echo "[Parasoft/Maven] Critical/High findings: $PARA_HIGH"
  fi
fi
```

---

## Step 7 — Scantist SCA

Scantist downloads its own JAR from the DTP server at runtime (`--network=host` is required
to reach `$DEVSECOPS_IMPORT_URL`). This is intentional — the JAR is not vendored.

### Scantist — JS project

Runs in parallel with other scanners.

```bash
if $HAS_PACKAGE_JSON && [ -n "$SCANTIST_IMAGE" ] && [ -n "$DEVSECOPS_IMPORT_URL" ]; then
  echo "[Scantist/JS] Starting scan in background..."
  docker run --rm \
    --network=host \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${SCANTIST_IMAGE}" \
    bash -c "
      curl -k ${DEVSECOPS_IMPORT_URL}/CA.pem --output CA.pem
      sudo \$JAVA_HOME/bin/keytool -cacerts -storepass changeit -noprompt \
        -trustcacerts -importcert -alias platformCA -file CA.pem

      curl -k ${DEVSECOPS_IMPORT_URL}/scantist-bom-detect.jar --output scantist-bom-detect.jar

      java -jar scantist-bom-detect.jar \
        -report_format xml \
        -checkCompliance \
        -branch ${BRANCH} \
        --debug \
        -jsScope prod

      # Rename report files: scan-*-<uuid>.xml → scantist-<uuid>.xml
      for file in ./devsecops_report/**/*.xml; do
        if [ -f \"\$file\" ]; then
          newname=\$(echo \"\$file\" | sed 's|scan-[^/]*-|scantist-|')
          mv \"\$file\" \"\$newname\"
        fi
      done

      cp -r ./devsecops_report /workspace/.appsec-results/scantist-js-report
    " > .appsec-results/scantist-js.log 2>&1 &
  SCANTIST_JS_PID=$!
  echo "[Scantist/JS] PID $SCANTIST_JS_PID"
fi
```

### Scantist — Maven project

Must run AFTER Parasoft Maven (needs compiled artifacts from `mvn clean install`).

```bash
if $HAS_POM && ! $HAS_GRADLE && [ -n "$SCANTIST_IMAGE" ] && [ -n "$DEVSECOPS_IMPORT_URL" ] && [ -n "$MAVEN_SETTINGS_XML" ]; then
  echo "[Scantist/Maven] Running (after Parasoft Maven artifacts)..."
  docker run --rm \
    --network=host \
    -v "$PWD:/workspace" \
    -w /workspace \
    "${APPSEC_REGISTRY}/${SCANTIST_IMAGE}" \
    bash -c "
      curl -k ${DEVSECOPS_IMPORT_URL}/scantist-bom-detect.jar --output scantist-bom-detect.jar

      # Build artifacts needed by Scantist (compile without re-running jtest)
      mvn clean install -s ${MAVEN_SETTINGS_XML} -DskipTests

      java -jar scantist-bom-detect.jar \
        -report_format xml \
        -checkCompliance \
        -branch ${BRANCH} \
        --debug

      for file in ./devsecops_report/**/*.xml; do
        if [ -f \"\$file\" ]; then
          newname=\$(echo \"\$file\" | sed 's|scan-[^/]*-|scantist-|')
          mv \"\$file\" \"\$newname\"
        fi
      done

      cp -r ./devsecops_report /workspace/.appsec-results/scantist-maven-report
    " 2>&1 | tee .appsec-results/scantist-maven.log
  echo "[Scantist/Maven] Done"
fi
```

---

## Step 8 — Trivy (container image scanning)

```bash
if [ -n "$TRIVY_TARGET" ] && [ -n "$TRIVY_IMAGE" ]; then
  echo "[Trivy] Scanning image: $TRIVY_TARGET"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PWD/.appsec-results:/results" \
    "${APPSEC_REGISTRY}/${TRIVY_IMAGE}" \
    trivy image \
      --format json \
      --output /results/trivy-results.json \
      "$TRIVY_TARGET"
  echo "[Trivy] Done"
else
  echo "[Trivy] Skipped — set TRIVY_TARGET and TRIVY_IMAGE to enable"
fi
```

---

## Step 9 — Wait for remaining background jobs

```bash
[ -n "$SCANTIST_JS_PID" ] && wait $SCANTIST_JS_PID && echo "[Scantist/JS] Done" || echo "[Scantist/JS] Failed — check .appsec-results/scantist-js.log"
```

---

## Step 10 — Parse results and severity gate

Parse each result file and build a summary table. Block if any CRITICAL or HIGH findings exist.

```bash
echo ""
echo "============================================================"
echo "  AppSec Scan Summary"
echo "============================================================"
printf "%-20s %-10s %-6s %-8s %-5s\n" "Scanner" "Critical" "High" "Medium" "Low"
printf "%-20s %-10s %-6s %-8s %-5s\n" "-------" "--------" "----" "------" "---"

TOTAL_CRITICAL=0
TOTAL_HIGH=0

# --- Fortify Python ---
if [ -f .appsec-results/fortify-python.fpr ]; then
  # FPR is a ZIP; count <Issue> tags as a proxy
  FORTIFY_PY_COUNT=$(unzip -p .appsec-results/fortify-python.fpr audit.fvdl 2>/dev/null | \
    grep -c '<Vulnerability>' || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "Fortify/Python" "-" "-" "-" "$FORTIFY_PY_COUNT total"
fi

# --- Fortify JS ---
if [ -f .appsec-results/fortify-js.fpr ]; then
  FORTIFY_JS_COUNT=$(unzip -p .appsec-results/fortify-js.fpr audit.fvdl 2>/dev/null | \
    grep -c '<Vulnerability>' || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "Fortify/JS" "-" "-" "-" "$FORTIFY_JS_COUNT total"
fi

# --- Pylint ---
if [ -f .appsec-results/pylint-report.json ]; then
  PY_FATAL=$(jq '[.[] | select(.type == "fatal" or .type == "error")] | length' \
    .appsec-results/pylint-report.json 2>/dev/null || echo 0)
  PY_WARN=$(jq '[.[] | select(.type == "warning")] | length' \
    .appsec-results/pylint-report.json 2>/dev/null || echo 0)
  PY_INFO=$(jq '[.[] | select(.type == "convention" or .type == "refactor")] | length' \
    .appsec-results/pylint-report.json 2>/dev/null || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "Pylint" "$PY_FATAL" "-" "$PY_WARN" "$PY_INFO"
  TOTAL_CRITICAL=$((TOTAL_CRITICAL + PY_FATAL))
fi

# --- ESLint ---
if [ -f .appsec-results/eslint.json ]; then
  ES_ERROR=$(jq '[.[].messages[] | select(.severity == 2)] | length' \
    .appsec-results/eslint.json 2>/dev/null || echo 0)
  ES_WARN=$(jq '[.[].messages[] | select(.severity == 1)] | length' \
    .appsec-results/eslint.json 2>/dev/null || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "ESLint" "$ES_ERROR" "-" "$ES_WARN" "-"
  TOTAL_CRITICAL=$((TOTAL_CRITICAL + ES_ERROR))
fi

# --- Parasoft ---
if [ -f .appsec-results/parasoft-reports/report.xml ]; then
  PARA_CRIT=$(xmllint --xpath \
    "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=1])" \
    .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
  PARA_HIGH=$(xmllint --xpath \
    "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=2])" \
    .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
  PARA_MED=$(xmllint --xpath \
    "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=3])" \
    .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
  PARA_LOW=$(xmllint --xpath \
    "count(/ResultsSession/CodingStandards/Rules/SeverityList/Severity[@id=4])" \
    .appsec-results/parasoft-reports/report.xml 2>/dev/null || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "Parasoft" "$PARA_CRIT" "$PARA_HIGH" "$PARA_MED" "$PARA_LOW"
  TOTAL_CRITICAL=$((TOTAL_CRITICAL + PARA_CRIT))
  TOTAL_HIGH=$((TOTAL_HIGH + PARA_HIGH))
fi

# --- Trivy ---
if [ -f .appsec-results/trivy-results.json ]; then
  TRIVY_CRIT=$(jq '[.Results[]? | .Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' \
    .appsec-results/trivy-results.json 2>/dev/null || echo 0)
  TRIVY_HIGH=$(jq '[.Results[]? | .Vulnerabilities[]? | select(.Severity == "HIGH")] | length' \
    .appsec-results/trivy-results.json 2>/dev/null || echo 0)
  TRIVY_MED=$(jq '[.Results[]? | .Vulnerabilities[]? | select(.Severity == "MEDIUM")] | length' \
    .appsec-results/trivy-results.json 2>/dev/null || echo 0)
  TRIVY_LOW=$(jq '[.Results[]? | .Vulnerabilities[]? | select(.Severity == "LOW")] | length' \
    .appsec-results/trivy-results.json 2>/dev/null || echo 0)
  printf "%-20s %-10s %-6s %-8s %-5s\n" "Trivy" "$TRIVY_CRIT" "$TRIVY_HIGH" "$TRIVY_MED" "$TRIVY_LOW"
  TOTAL_CRITICAL=$((TOTAL_CRITICAL + TRIVY_CRIT))
  TOTAL_HIGH=$((TOTAL_HIGH + TRIVY_HIGH))
fi

echo "============================================================"
printf "%-20s %-10s %-6s\n" "TOTAL" "$TOTAL_CRITICAL" "$TOTAL_HIGH"
echo "============================================================"

# Final gate
if [ "$TOTAL_CRITICAL" -gt 0 ] || [ "$TOTAL_HIGH" -gt 0 ]; then
  echo ""
  echo "GATE FAILED: $TOTAL_CRITICAL Critical and $TOTAL_HIGH High findings detected."
  echo "Fix all Critical and High findings before pushing."
  echo "Full results in .appsec-results/"
  exit 1
else
  echo ""
  echo "GATE PASSED: No Critical or High findings. Results in .appsec-results/"
fi
```

---

## Environment variable reference

Set these in your shell or `.env` file (do NOT commit credentials):

```bash
export APPSEC_REGISTRY="registry.company.com/security"
export FORTIFY_PY_IMAGE="fortify-sast:latest-jdk17"
export FORTIFY_JS_IMAGE="fortify-sast:latest-jdk17"
export PARASOFT_IMAGE="parasoft-jtest:latest"
export PYLINT_IMAGE="pylint:latest"
export ESLINT_IMAGE="eslint:latest"
export SCANTIST_IMAGE="scantist:latest"
export TRIVY_IMAGE="trivy:latest"
export DEVSECOPS_IMPORT_URL="https://dtp.company.com"
export APP_NAME="my-app"
export SOURCE_PATH="src"
export ESLINT_CONFIG_FILE=".eslintrc.js"
export MAVEN_SETTINGS_XML="/home/user/.m2/settings.xml"
export TRIVY_TARGET="my-app:1.0.0"
export CI_PROJECT_URL="https://gitlab.company.com/mygroup/my-app"
```

---

## What NOT to do

- Do not add `--upload-results` or `fortifyclient` steps — scan-only is sufficient locally.
- Do not remove `--network=host` from Scantist — it needs to reach the DTP server.
- Do not skip the `wait` calls — parallel scanners must complete before gating.
- Do not commit `.appsec-results/` — add it to `.gitignore`.
- Do not hard-code registry URLs or credentials in SKILL.md or code.
- Do not run Scantist Maven before Parasoft Maven — it requires compiled artifacts.

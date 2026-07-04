# AppSec Scan — Update Guide

This guide explains how to keep `appsec-scan` in sync with your GitLab CI components.

---

## File structure

```
skills/appsec-scan/
├── SKILL.md                ← orchestration only — edit rarely (see "When to edit SKILL.md")
├── UPDATE-GUIDE.md         ← this file
├── config/
│   ├── scanner-preferences.yaml
│   └── PREFERENCES.md
├── reference/
│   └── catalog/
├── scripts/
│   └── catalog.sh
└── scanners/
    ├── fortify-python.sh   ← mirrors devops/ci-catalogue/fortify-scan-python3
    ├── fortify-js.sh       ← mirrors devops/ci-catalogue/fortify-scan-js
    ├── parasoft-gradle.sh  ← mirrors devops/ci-catalogue/parasoft-scan-gradle
    ├── parasoft-maven.sh   ← mirrors devops/ci-catalogue/parasoft-scan-maven
    ├── pylint.sh           ← mirrors devops/ci-catalogue/pylint
    ├── eslint.sh           ← mirrors devops/ci-catalogue/eslint
    ├── scantist-js.sh      ← mirrors devops/ci-catalogue/scantist-js-scan
    ├── scantist-maven.sh   ← mirrors devops/ci-catalogue/scantist-maven-scan (post-Maven)
    ├── gitlab-sast.sh
    ├── gitlab-dependency-scanning.sh
    ├── gitlab-container-scanning.sh
    ├── secret-detection.sh ← mirrors gitlab.com/components/secret-detection
    └── trivy.sh            ← mirrors devops/ci-catalogue/trivy-scan
```

Each scanner file has a header block:
```bash
# Scanner      : <tool name>
# CI component : <component path>@~latest
# Last synced  : <date>
# Image env var: <env var name>
```

This header is your change log for that scanner. Update `Last synced` every time you sync.

---

## Scenario 1 — CI component script changed

A CI component had its `script:` block updated (new flags, new steps, different commands).

**Steps:**

1. Open the corresponding `scanners/<name>.sh` file.
2. Find the `# SCAN — mirrors the CI component script exactly` section.
3. Replace the commands inside that section with the new CI component commands.
4. If the component added `before_script` or `after_script` blocks, add them to
   the SETUP section or the AFTER SCRIPT section respectively.
5. Update the `# Last synced` header line to today's date.
6. Commit: `git commit -m "sync: update <scanner> to match CI component change"`

**Example — Fortify Python added a new `-python-path` flag:**
```bash
# Before (in fortify-python.sh SCAN section):
sourceanalyzer -b "$APP_NAME" -debug-verbose -python-version 3 "$SOURCE_PATH"

# After:
sourceanalyzer -b "$APP_NAME" -debug-verbose -python-version 3 \
  -python-path "$(python3 -c 'import sys; print(":".join(sys.path))')" \
  "$SOURCE_PATH"
```

---

## Scenario 2 — New language added to an existing scanner

The CI team ships a new component variant for a language that wasn't supported before
(e.g. Fortify for Go, Scantist for Gradle).

**Steps:**

1. Create a new file in `scanners/` following the naming pattern:
   `<scanner>-<language>.sh` (e.g. `fortify-go.sh`, `scantist-gradle.sh`)

2. Use an existing scanner file as a template. Copy the header block and update:
   - `Scanner`, `Language`, `CI component`, `Last synced`, `Image env var`

3. Fill in the SETUP and SCAN sections with the CI component's script commands.

4. Open `SKILL.md` and add a detection block in **Step 3** for the new scanner.
   Copy an existing block (e.g. the Fortify Python block) and adjust:
   - The detection condition (`HAS_GO`, `HAS_GRADLE`, etc.)
   - The image env var name
   - The scanner file name
   - The PID variable name

   **Example — adding Fortify Go:**
   ```bash
   ### Fortify SAST — Go
   # Applies when: Go project detected. Runner: scanners/fortify-go.sh.
   if $HAS_GO && [ -n "$FORTIFY_GO_IMAGE" ]; then
     echo "[Fortify/Go] Starting in background..."
     docker run --rm \
       -v "$PWD:/workspace" \
       -v "$SCANNERS_DIR/fortify-go.sh:/runner.sh:ro" \
       -w /workspace \
       -e APP_NAME="$APP_NAME" \
       -e SOURCE_PATH="$SOURCE_PATH" \
       "${APPSEC_REGISTRY}/${FORTIFY_GO_IMAGE}" \
       bash /runner.sh > .appsec-results/fortify-go.log 2>&1 &
     FORTIFY_GO_PID=$!
   fi
   ```

5. Add the new PID to the `wait` loop in Step 3 of SKILL.md:
   ```bash
   for pid_var in FORTIFY_PY_PID FORTIFY_JS_PID FORTIFY_GO_PID ...
   ```

6. Add the new env var to the Prerequisites table in SKILL.md.

7. If the new scanner produces output, add a parse block in Step 4 of SKILL.md.

8. Commit: `git commit -m "feat: add Fortify Go scanner to appsec-scan"`

---

## Scenario 3 — Scanner image name or tag changed

The Platform Team renamed or retagged a scanner image.

**Steps:**

1. Update the env var default in the Prerequisites table in `SKILL.md`.
2. No change needed to the scanner files — they use env vars, not hardcoded names.
3. Remind developers to update their shell profile export:
   ```bash
   export FORTIFY_PY_IMAGE="fortify-sast-python:v2-jdk21"
   ```

---

## Scenario 4 — New setup step required before scanning

The CI component now requires a build step before the scan
(e.g. Python Fortify needs `uv sync`, Go Fortify needs `go build`).

**Steps:**

1. Open the relevant `scanners/<name>.sh`.
2. Add the step to the `# SETUP` section — the block that runs before the SCAN section.
3. Document WHY the setup step is needed with a comment.
4. Update `Last synced`.

**Example — Python Fortify adding uv sync (already done):**
```bash
# SETUP — sync dependencies for full data flow analysis
if command -v uv >/dev/null 2>&1; then
  uv sync --all-extras 2>/dev/null || true
elif [ -f requirements.txt ]; then
  pip install -r requirements.txt --quiet 2>/dev/null || true
fi
```

---

## Scenario 5 — Scanner removed from CI pipeline

The CI team retires a scanner entirely.

**Steps:**

1. Remove the `scanners/<name>.sh` file.
2. Remove the corresponding detection block from SKILL.md Step 3.
3. Remove the PID variable from the `wait` loop.
4. Remove the parse block from SKILL.md Step 4.
5. Remove the env var from the Prerequisites table.
6. Commit: `git commit -m "chore: remove <scanner> — retired from CI pipeline"`

## Scenario 6 — Refreshing vendored catalog snapshots

Quarterly or after a component release, run:

```bash
bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh resolve https://gitlab.com <component-path> /tmp/catalog-refresh
```

for each of: `components/sast/sast`, `components/secret-detection/secret-detection`, `components/dependency-scanning/main`, `components/container-scanning/container-scanning`

Copy the new `<tag>/template.yml` + `README.md` from the refresh dir into `reference/catalog/<component-path>/<tag>/` (keep prior tag dirs).

Run `check-drift` for each component against its runner script and update the runner's `# Last synced` header.

Commit as: `chore(appsec): refresh catalog snapshots to <tags>`

---

## When to edit SKILL.md vs. scanner files

| Change | Edit |
|---|---|
| CI component script changed | `scanners/<name>.sh` only |
| New language variant for existing scanner | New `scanners/<name>-<lang>.sh` + one block in SKILL.md |
| New scanner entirely | New `scanners/<name>.sh` + detection + wait + parse in SKILL.md |
| Scanner image renamed/retagged | SKILL.md Prerequisites table only |
| New setup step before scan | `scanners/<name>.sh` SETUP section only |
| Scanner retired | Remove scanner file + remove blocks from SKILL.md |

## GitLab Secret Detection notes

The Secret Detection scanner mirrors the GitLab CI/CD Catalog component:

- Image shape: `$image_prefix/secrets:$image_tag$image_suffix`
- Default local image: `${SECRET_DETECTION_IMAGE_PREFIX:-$APPSEC_REGISTRY}/secrets:${SECRET_DETECTION_IMAGE_TAG:-7}${SECRET_DETECTION_IMAGE_SUFFIX:-}`
- Script block: `/analyzer run`
- Report artifact: `gl-secret-detection-report.json`

Use `SECRET_DETECTION_IMAGE` to override the full image path, or set
`SECRET_DETECTION_IMAGE_PREFIX`, `SECRET_DETECTION_IMAGE_TAG`, and
`SECRET_DETECTION_IMAGE_SUFFIX` to match your internal mirror. For public-image
smoke testing, use:

```bash
export SECRET_DETECTION_IMAGE="registry.gitlab.com/security-products/secrets:7"
```

When the GitLab component changes, update `scanners/secret-detection.sh`, the
Secret Detection Docker block in `SKILL.md`, and the smoke test parser together.
Keep result summaries redacted: never print raw values from
`gl-secret-detection-report.json`.

**Never embed scanner commands directly in SKILL.md.** All commands go in `scanners/`.

---

## Testing your changes locally

Before committing a scanner update, verify it works end-to-end:

```bash
# 1. Set required env vars
export APPSEC_REGISTRY="registry.company.com/security"
export FORTIFY_PY_IMAGE="fortify-sast:latest-jdk17"
export DEVSECOPS_IMPORT_URL="https://dtp.company.com"

# 2. Resolve scanner dir
SKILL_DIR="path/to/skills/appsec-scan"
SCANNERS_DIR="$SKILL_DIR/scanners"

# 3. Run just the updated scanner in isolation
docker run --rm \
  -v "$PWD:/workspace" \
  -v "$SCANNERS_DIR/fortify-python.sh:/runner.sh:ro" \
  -w /workspace \
  -e APP_NAME="test-app" \
  -e SOURCE_PATH="src" \
  "${APPSEC_REGISTRY}/${FORTIFY_PY_IMAGE}" \
  bash /runner.sh

# 4. Check the output
ls -la .appsec-results/
```

If the isolated run passes, run the full `appsec-scan` skill to confirm the
orchestration still works end-to-end.

---

## Quarterly sync reminder

Review all scanner files against their CI components on the first Monday of
March, June, September, and December. Check for:

- New flags added to the component's script block
- Changes to the gate conditions (severity thresholds)
- New `before_script` or `after_script` steps
- Image tag updates

Drift detection now runs automatically at every scan run via `scripts/catalog.sh check-drift`; the quarterly task is refreshing snapshots and `Last-synced` headers (Scenario 6).

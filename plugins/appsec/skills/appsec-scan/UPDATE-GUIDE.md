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
│       └── lobster-thermidor/devops/ci-catalogue/
│           ├── fortify-sast/fortify-sast/25.2.0/
│           │   ├── template.yml
│           │   ├── README.md
│           │   └── AGENTS.md       ← agent-oriented usage reference
│           ├── dependency-scanning/dependency-scanning/1.0.0/
│           ├── secret-detection/secret-detection/1.0.0/
│           └── container-scanning/container-scanning/1.0.0/
├── scripts/
│   └── catalog.sh
└── scanners/
    ├── fortify-sast.sh                     ← mirrors lobster-thermidor/.../fortify-sast
    ├── gitlab-dependency-scanning.sh       ← mirrors lobster-thermidor/.../dependency-scanning
    ├── secret-detection.sh                 ← mirrors lobster-thermidor/.../secret-detection
    ├── gitlab-container-scanning.sh        ← mirrors lobster-thermidor/.../container-scanning
    └── preflight.sh
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
6. If the scanner's output schema changed, update the corresponding parser in `scripts/normalize.py`.
7. Commit: `git commit -m "sync: update <scanner> to match CI component change"`

**Example — Fortify added a new `-filter-file` flag:**
```bash
# Before (in fortify-sast.sh SCAN section):
sourceanalyzer -b "$APP_NAME" -debug-verbose -python-version 3 "$SOURCE_PATH"

# After:
sourceanalyzer -b "$APP_NAME" -debug-verbose -python-version 3 \
  -filter-file /workspace/filter_list.txt \
  "$SOURCE_PATH"
```

---

## Scenario 2 — New language added to Fortify SCA

The upstream component added a new language variant. **This is not hypothetical:
fortify-sast@25.2.0 already declares `go`**, and `scanners/fortify-sast.sh` has a
`go)` arm that emits `NEEDS-MAPPING:` because the correct `sourceanalyzer`
invocation for Go has not been mirrored yet. Completing that is the worked
example below.

You will normally learn about this from a `CONTRACT-DRIFT:` line naming a new
`input.language.option=<lang>`.

**Steps:**

1. Open `scanners/fortify-sast.sh` and add (or replace the `NEEDS-MAPPING:`
   stub with) a real language branch in the `case "$FORTIFY_LANGUAGE" in` block,
   mirroring the component's script for that language.
2. Open `scripts/run-scan.sh` and add the new project-type detection flag
   (e.g. `HAS_GO`) and extend the language auto-detection precedence chain.
   Without this, the language is only reachable by setting `FORTIFY_LANGUAGE`
   explicitly, and a Go-only repo produces a SAST coverage gap.
3. Add the new language to the Prerequisites table `FORTIFY_LANGUAGE` row in SKILL.md.
4. **Regenerate the contract** so the option is recorded as expected:
   `bash scripts/catalog.sh contract <component> <cache> > scanners/fortify-sast.contract`
   (keep the `#` header — see Scenario 6). `tests/test_catalog.py` asserts every
   declared language has a case arm, so this fails loudly if step 1 was skipped.
5. Update `# Last synced` in `fortify-sast.sh`.
6. `python3 -m pytest tests/ -q`, then commit.

No new scanner file is needed — Fortify SCA is a single multi-language runner.

---

## Scenario 3 — Scanner image name or tag changed

The Platform Team renamed or retagged a scanner image.

**Steps:**

1. Edit that category's `image:` in `config/scanner-preferences.yaml` — that
   pinned ref is what runs. Nothing else to touch; `scripts/load-prefs.sh`
   exports it at Step 1.5.
2. If changing the Fortify image specifically, update `FORTIFY_SAST_IMAGE` in
   the profile's category block and remind developers who override via env var
   to update `~/.bashrc` / `~/.zshrc` accordingly.
3. No change needed to the scanner files — they use env vars, not hardcoded names.

---

## Scenario 4 — New setup step required before scanning

The CI component now requires a build step before the scan
(e.g. Fortify Maven needs `mvn dependency:resolve` first).

**Steps:**

1. Open the relevant `scanners/<name>.sh`.
2. Add the step to the `# SETUP` section — the block that runs before the SCAN section.
3. Document WHY the setup step is needed with a comment.
4. Update `Last synced`.

---

## Scenario 5 — Scanner removed from CI pipeline

The CI team retires a scanner category entirely.

**Steps:**

1. Remove the `scanners/<name>.sh` file.
2. Remove the corresponding invocation block from `scripts/run-scan.sh`.
3. Remove the parse/triage logic from `scripts/normalize.py`.
4. Remove the env var from the Prerequisites table in SKILL.md.
5. Remove the category block from `config/scanner-preferences.yaml`.
6. Commit: `git commit -m "chore: remove <scanner> — retired from CI pipeline"`

---

## Scenario 6 — Refreshing vendored catalog snapshots

Quarterly, or after a component release. One command does the whole thing —
resolve every enabled component at `~latest`, copy `template.yml`, `README.md`
and `AGENTS.md` into `reference/catalog/<component>/<tag>/`, stamp the
provenance header, and regenerate `scanners/*.contract`:

```bash
cd plugins/appsec/skills/appsec-scan

# public catalogue (private projects, so a read_api PAT is required)
bash scripts/revendor.sh https://gitlab.com GITLAB_READ_TOKEN

# an internal instance that serves the catalogue anonymously
bash scripts/revendor.sh https://gitlab.internal.company.com
```

Prior tag directories are left in place; the resolver picks the highest.

**It refuses to vendor a component that resolved `[offline-fallback]`.** That
would copy the existing snapshot onto itself and make a stale component look
freshly confirmed. If you see `REFUSED`, the instance was unreachable or the
token was rejected — fix that and re-run. Nothing is written for a refused
component.

**Airgap note:** run this against your *internal* instance after publishing the
components there. Snapshots vendored from gitlab.com describe gitlab.com's
components; serving those as the offline fallback inside your airgap would
report a component shape you never published.

Review the diff: **every changed line is a real upstream change**. A new
`input.<name>.option=` means the component gained a capability the runner may
not implement — check the runner has a matching arm, or make it emit
`NEEDS-MAPPING:` (see `tests/test_catalog.py::ContractCoverageTest`). Never
hand-edit a contract to silence drift; that re-creates the false-clean these
files exist to prevent.

Run `check-drift` for each component against its runner script and update the
runner's `# Last synced` header.

Commit as: `chore(appsec): refresh catalog snapshots to <tags>`

**Note on fortify-sast@25.2.0:** the AGENTS.md in this snapshot was vendored
from HEAD (the file was added upstream after the 25.2.0 tag was cut, on
2026-07-15). Future snapshot refreshes will pick it up from the tag directly.

---

## When to edit SKILL.md vs. scanner files

| Change | Edit |
|---|---|
| CI component script changed | `scanners/<name>.sh` only (+ `normalize.py` if schema changed) |
| New language variant for Fortify | `scanners/fortify-sast.sh` case block + detection in `scripts/run-scan.sh` |
| New scanner category entirely | New `scanners/<name>.sh` + `scripts/run-scan.sh` invocation + `scripts/normalize.py` parser |
| Scan orchestration logic changed | `scripts/run-scan.sh` |
| Report parsing / triage / gate | `scripts/normalize.py` |
| Scanner image renamed/retagged | `config/scanner-preferences.yaml` `image:` |
| Component version pin changed | `config/scanner-preferences.yaml` `version:` + optional snapshot refresh |
| New setup step before scan | `scanners/<name>.sh` SETUP section only |
| Scanner retired | Remove scanner file + remove from `run-scan.sh` + `normalize.py` |

## GitLab Secret Detection notes

The Secret Detection scanner mirrors the GitLab CI/CD Catalog component:

- Image: the active profile's `secret_detection.image:` (full ref), exported as
  `SECRET_DETECTION_IMAGE` by `scripts/load-prefs.sh` in Step 1.5; a pre-set
  `SECRET_DETECTION_IMAGE` env var overrides it for one run.
- Script block: `/analyzer run`
- Report artifact: `gl-secret-detection-report.json`

For public-image smoke testing, use the image from the vendored snapshot:

```bash
export SECRET_DETECTION_IMAGE="registry.gitlab.com/security-products/secrets:7"
```

When the GitLab component changes, update `scanners/secret-detection.sh`, the
invocation block in `scripts/run-scan.sh`, and `scripts/normalize.py` together.
Keep result summaries redacted: never print raw values from
`gl-secret-detection-report.json`.

**Never embed scanner commands directly in SKILL.md.** All commands go in `scanners/`.

---

## Testing your changes locally

Before committing a scanner update, verify it works end-to-end:

```bash
# 1. Set required env vars
export FORTIFY_SAST_IMAGE="registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/fortify-sca:25.2.0-jdk17-review"
export FORTIFY_LANGUAGE="maven"

# 2. Resolve scanner dir
SKILL_DIR="path/to/skills/appsec-scan"
SCANNERS_DIR="$SKILL_DIR/scanners"

# 3. Run just the updated scanner in isolation
docker run --rm \
  -v "$PWD:/workspace" \
  -v "$SCANNERS_DIR/fortify-sast.sh:/runner.sh:ro" \
  -w /workspace \
  -e APP_NAME="test-app" \
  -e SOURCE_PATH="src" \
  -e FORTIFY_LANGUAGE="maven" \
  "${FORTIFY_SAST_IMAGE}" \
  bash /runner.sh

# 4. Check the output
ls -la .appsec-results/

# 5. Dry-run the full orchestrator (no containers)
APPSEC_PROFILE=catalog bash "$SKILL_DIR/scripts/run-scan.sh" --dry-run

# 6. Test normalize.py with existing results (empty RAN list for unit test)
python3 "$SKILL_DIR/scripts/normalize.py" .appsec-results --ran ""

# 7. Budget check (CI enforces ≤275 lines / ≤13800 chars)
wc -l "$SKILL_DIR/SKILL.md" && wc -c "$SKILL_DIR/SKILL.md"
```

If the isolated run passes, run the full orchestrator to confirm end-to-end orchestration.

## Opt-in docker smoke tests

Two tests pull real public analyzer images and are skipped unless explicitly
enabled (they need docker + internet, so repo CI skips them too):

```bash
RUN_SECRET_DETECTION_SMOKE=1 python3 -m pytest tests/test_secret_detection.py -v
RUN_FORTIFY_SAST_SMOKE=1     python3 -m pytest tests/test_skill_doc.py -v
```

Run them before releasing changes to `scripts/run-scan.sh` (orchestration)
or `scanners/*.sh` (scanner commands).

---

## Quarterly sync reminder

Review all scanner files against their CI components on the first Monday of
March, June, September, and December. Check for:

- New flags added to the component's script block
- Changes to the gate conditions (severity thresholds)
- New `before_script` or `after_script` steps
- Image tag updates

Drift detection runs automatically at every scan via `scripts/catalog.sh check-drift`, in two forms: **image drift** (configured `image:` vs the component's effective job image) and **contract drift** (declared inputs, `options:` and report artifacts vs `scanners/<runner>.contract`). The quarterly task is refreshing snapshots, contracts and `Last synced` headers (Scenario 6).

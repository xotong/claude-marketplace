---
name: appsec-scan
description: >
  Run the same security scanners as CI — locally, using identical container images —
  before pushing to GitLab, driven by admin-managed scanner preferences and the
  private GitLab CI/CD Catalog at lobster-thermidor/devops/ci-catalogue with
  per-component version pinning (~latest or exact tag). Categories:
  SAST (Fortify SCA, multi-language: maven, gradle, python, javascript),
  Dependency Scanning (GitLab SBOM), Secret Detection (GitLab/Gitleaks),
  Container Scanning (GTCS). Single-command scan via run-scan.sh; normalized
  findings with verification statuses in findings.triaged.json; approval-gated
  fix loop (fix-branch.sh, ≤5 iterations) and guided triage plan (TRIAGE.md).
  Use when the user says: "appsec scan", "run security scanners", "run Fortify",
  "pre-push security check", "CI security pipeline locally", "mirror CI scanners",
  "container security scan", "SCA scan", "SAST scan", "dependency scan",
  "secret scan", "secret detection", "security before merge", "scan profile",
  "catalog components", "triage plan", "fix security findings".
  Do NOT activate for general code review, unit testing, or lint-only requests.
---

# AppSec Scan — Catalog-Driven CI Mirror

Run the same scanner images your GitLab CI pipeline uses, locally. `scripts/run-scan.sh` orchestrates all four scanners; `scripts/normalize.py` emits `.appsec-results/findings.triaged.json` with per-finding `verification_status` and drives the severity gate. `scripts/fix-branch.sh` guards the fix loop. Scan mechanics live in `scripts/`, scanner commands in `scanners/` — never edit SKILL.md for those. New in v3.1: `run-scan.sh`, `normalize.py`, `fix-branch.sh`, `resolve-python.sh`, `CHANGELOG.md`, `MIGRATION.md`. **Config:** `config/scanner-preferences.yaml`. **Scanners:** `scanners/*.sh`. **Versions/pins:** `version:` in category block → UPDATE-GUIDE.md.

## Prerequisites

| Variable | Description |
|---|---|
| `APPSEC_PROFILE` | Active profile (`default_profile` from config) |
| `FORTIFY_LANGUAGE` | `maven`\|`gradle`\|`python`\|`javascript`; auto-detected |
| `CS_IMAGE` | Container image:tag for Container Scanning (optional) |
| `APP_NAME` | Application name (default: `basename $PWD`) |
| `SOURCE_PATH` | Source dir for Fortify (default: `src`) |
| `CI_PROJECT_URL` | GitLab project URL (Fortify source control config) |

---

## Step 1 — Locate the skill's directories

The scanner scripts are relative to the skill's own directory, not the project
being scanned. Resolve this path first — subsequent steps depend on it.

```bash
export SKILL_DIR="${SKILL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)}"
export SCANNERS_DIR="$SKILL_DIR/scanners"
export SCRIPTS_DIR="$SKILL_DIR/scripts"
if [ ! -d "$SCANNERS_DIR" ] || [ ! -d "$SCRIPTS_DIR" ]; then
  echo "ERROR: skill directory not found (SKILL_DIR='$SKILL_DIR')." >&2
  echo "Set it explicitly and re-run, e.g.:" >&2
  echo "  export SKILL_DIR=/abs/path/to/plugins/appsec/skills/appsec-scan" >&2
  return 1 2>/dev/null || exit 1
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
# PYTHON_INSTALL_URL, and ENABLED_COMPONENTS (space-separated "component|version|runner" triples).

# Detect the container runtime (docker or podman) — hard requirement.
export RUNTIME="$(CONTAINER_RUNTIME="$CONTAINER_RUNTIME" bash "$SCRIPTS_DIR/detect-runtime.sh")" || {
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

## Step 3 — Run the scan

```bash
bash "$SCRIPTS_DIR/run-scan.sh"
```

run-scan.sh invokes `"$RUNTIME" run` per scanner and `"$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"` before Secret Detection. `resolve-jq.sh` and `container-target.sh` are used internally (`GITLAB_FEATURES=dependency_scanning` for Dependency Scanning). A scanner with no report becomes a HIGH coverage finding (HAS_MISSING_REPORT semantics — the result is NOT an all-clear). Stdout: summary from `normalize.py`; exit 1 → findings, go Step 4; exit 0 → done. Flags: `--dry-run`; `--only <category>` (sast|dependency_scanning|secret_detection|container_scanning).

---

## Step 4 — Review findings

Read `.appsec-results/findings.triaged.json`. Present each finding: severity, name, scanner, location, `verification_status`, `triage_reason`. The model may override a `verification_status` with explicit reasoning. For Secret Detection findings, show only the redacted list from the summary (`Secret Detection findings (redacted)`) — never read raw values from `gl-secret-detection-report.json`.

---

## Step 5 — Fix loop

```bash
bash "$SCRIPTS_DIR/fix-branch.sh" --init
```

Names the branch `appsec/fix-<YYYYMMDD>-<shortsha>`. Ask for approval once before making changes — it will create a new branch. Loop maximum **5 iterations**: apply fixes → rescan ONLY the affected category (`bash "$SCRIPTS_DIR/run-scan.sh" --only <category>`; for secret findings, rerun only GitLab Secret Detection first) → `bash "$SCRIPTS_DIR/fix-branch.sh" --check-progress <prev> <curr>` (exits 1 on cap/no-progress → stop). When the loop ends, run the app's relevant tests. Never push or open an MR without the user explicitly asking. Never rewrite git history.

---

## Step 6 — Generate the triage plan (TRIAGE.md)

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

Use **appsec-dast-sim** from this same plugin for design-time DAST (no running app required).

---

## What NOT to do

- Do not edit scan mechanics or scanner commands in this file — edit `scripts/run-scan.sh` and `scanners/*.sh` respectively
- Do not add `fortifyclient` upload steps — scan-only is the local model
- Do not print raw secret values from `gl-secret-detection-report.json`
- Do not treat removing a detected value from source as credential rotation
- Do not commit `.appsec-results/` to git
- Do not contact any network endpoint other than the active profile's
  `gitlab_instance` (catalog metadata) and the configured image registries
- Do not rewrite git history, and do not push or open MRs without the user
  explicitly asking

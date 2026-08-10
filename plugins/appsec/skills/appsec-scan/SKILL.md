---
name: appsec-scan
description: >
  Run the same security scanners as CI — locally, using identical container images —
  before pushing to GitLab, driven by admin-managed scanner preferences and the
  private GitLab CI/CD Catalog at lobster-thermidor/devops/ci-catalogue with
  per-component version pinning (~latest or exact tag). Categories:
  SAST (Fortify SCA, multi-language: maven, gradle, python, javascript, go),
  Dependency Scanning (GitLab SBOM), Secret Detection (GitLab/Gitleaks),
  Container Scanning (GTCS). Single-command scan via run-scan.sh; normalized
  findings with verification statuses in findings.triaged.json; approval-gated
  fix loop (fix-branch.sh, ≤5 iterations) and guided triage plan (TRIAGE.md).
  Use when the user says: "appsec scan", "run security scanners", "run Fortify",
  "pre-push security check", "CI security pipeline locally", "mirror CI scanners",
  "security before merge", "scan profile", "catalog components", "triage plan",
  "fix security findings", "do all security scans", "full security scan",
  "scan everything", "is this safe to push".
  Also activate for a SINGLE category and scan only that one (Step 0 routes):
  SAST — "SAST scan", "static analysis", "run Fortify", "scan my code";
  Dependency — "dependency scan", "SCA scan", "check my dependencies",
  "any vulnerable libraries", "CVE check", "SBOM";
  Secrets — "secret scan", "secret detection", "any hardcoded secrets",
  "leaked credentials", "did I commit a key", "gitleaks";
  Container — "container scan", "image scan", "scan my Docker image", "GTCS".
  Do NOT activate for general code review, unit testing, or lint-only requests.
---

# AppSec Scan — Catalog-Driven CI Mirror

Run the same scanner images your GitLab CI pipeline uses, locally. `scripts/run-scan.sh` orchestrates all four scanners; `scripts/normalize.py` emits `.appsec-results/findings.triaged.json` with per-finding `verification_status` and drives the severity gate. `scripts/fix-branch.sh` guards the fix loop. **Config:** `config/scanner-preferences.yaml`. **Versions/pins:** `version:` in category block → UPDATE-GUIDE.md.

**Shell session:** see the shell contract in Step 1 — bash, one invocation per step. `run-scan.sh` self-locates and self-loads (including the runtime), so Steps 3 and 5 are safe standalone.
**Exit-code contract:** `run-scan.sh` exits 0 (gate passed), 1 (gate failed / findings present), 2 (usage/config error — e.g. unrecognised `ci_gate` value).

## Prerequisites

| Variable | Description |
|---|---|
| `APPSEC_PROFILE` | Active profile (`default_profile` from config) |
| `FORTIFY_LANGUAGE` | `maven`\|`gradle`\|`python`\|`javascript`\|`go`; auto-detected |
| `CS_IMAGE` | Container image:tag for Container Scanning (optional) |
| `APP_NAME` | Application name (default: `basename $PWD`) |
| `SOURCE_PATH` | Source dir for Fortify (default: `src`) |

---

## Step 0 — Decide what to scan

Set `SCAN_SCOPE` from the user's words **before** running anything.

| The user asked about | `SCAN_SCOPE` |
|---|---|
| their code, SAST, static analysis, Fortify | `sast` |
| dependencies, libraries, packages, SCA, CVEs, SBOM | `dependency_scanning` |
| secrets, credentials, API keys, tokens, gitleaks | `secret_detection` |
| a container, an image, Docker, GTCS | `container_scanning` |
| everything, a full scan, pushing safely, or bare `/appsec-scan` | `all` |
| anything you are not sure about | **ask — below** |

**When unsure, ask — never guess.** Use `AskUserQuestion` with `multiSelect: true`.
Many developers cannot tell these categories apart, so label by what the developer
would recognise, not by tool name:

- `Everything (recommended)` — all four; exactly what CI will run
- `My source code` — injection, unsafe calls, insecure patterns in code you wrote
- `My dependencies` — known CVEs in libraries you pull in
- `Hardcoded secrets` — keys, tokens, passwords committed by accident
- `My container image` — OS and package CVEs in the image you ship

Map the answer back to the table's `SCAN_SCOPE` values. If several categories are
picked but not all four, run Step 3 once per category.

A scoped scan still reports the categories it did **not** cover. Never present a
scoped result as "you are clear to push."

---

## Step 1 — Locate the skill's directories

The scanner scripts live beside this file, not in the project being scanned.
You read this file from disk, so you already know its directory — that is
`SKILL_DIR`; substitute the real absolute path below. Do **not** derive it from
`$0` or `${BASH_SOURCE[0]}`: those resolve to your shell and yield `/bin`.

```bash
export SKILL_DIR=/absolute/path/to/plugins/appsec/skills/appsec-scan
export SCANNERS_DIR="$SKILL_DIR/scanners"
export SCRIPTS_DIR="$SKILL_DIR/scripts"
[ -d "$SCANNERS_DIR" ] && [ -d "$SCRIPTS_DIR" ] || {
  echo "ERROR: wrong SKILL_DIR='$SKILL_DIR'" >&2; exit 1; }
```

**Shell contract — applies to every snippet in this file.** Run them with
`bash`, not your login shell, and send each step's commands as ONE invocation.
Two reasons, both of which fail silently rather than loudly: exports do not
survive between separate tool calls, and zsh (the macOS default) does not
word-split unquoted variables the way these snippets expect. Every script here
self-loads what it needs, so a step that only invokes a script is safe alone.

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
  return 1 2>/dev/null || exit 1
}
eval "$PREFS_ENV"
# Now set: APPSEC_PROFILE, APPSEC_AIRGAP, CONTAINER_RUNTIME, GITLAB_INSTANCE,
# CATALOG_AUTH_ENV, FORTIFY_SAST_IMAGE, SECRET_DETECTION_IMAGE, GITLAB_DS_IMAGE,
# GITLAB_CS_IMAGE (all four may be empty — see below), RUN_FORTIFY_SAST,
# RUN_GITLAB_DS, RUN_SECRET_DETECTION, RUN_GITLAB_CS, ENABLED_COMPONENTS
# ("component|version|runner|image|category" tuples), plus the jq/python,
# registry and airgap settings listed in load-prefs.sh's header.

# Detect the container runtime (docker or podman) — hard requirement.
RUNTIME="$(CONTAINER_RUNTIME="$CONTAINER_RUNTIME" bash "$SCRIPTS_DIR/detect-runtime.sh")" || {
  echo "ERROR: no container runtime (docker or podman) found"
  return 1 2>/dev/null || exit 1
}
export RUNTIME

echo "Profile: $APPSEC_PROFILE   GitLab: $GITLAB_INSTANCE   Runtime: $RUNTIME   Airgap: $APPSEC_AIRGAP"
```

- An empty `*_IMAGE` is normal: `image:` is optional in config, and under the
  default `image_policy: follow-component` Step 3 derives the image from the
  component template. A `*_IMAGE` env var set before the run still wins; an image
  that can be neither derived nor configured stops the scan (never a silent skip).
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
  bash "$SCANNERS_DIR/preflight.sh" || { return 1 2>/dev/null || exit 1; }
```

If preflight fails, show its output to the user and stop — its error lines name
exactly which variables to set. Never start scanners against an incomplete
environment.

---

## Step 2.5 — Resolve CI/CD Catalog components (every run)

For every **enabled** category component in the active profile, resolve the
component against the catalog and check drift. `scripts/catalog.sh` is the only
thing that talks to the network, and only to `$GITLAB_INSTANCE`.

```bash
bash "$SCRIPTS_DIR/resolve-components.sh"
```

It resolves every enabled component, checks each for drift, self-loads
preferences, and prints a ready-made resolution table — one row per component,
e.g. `| lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast | 25.2.0
| online | — |`. Show that table to the user verbatim before scanning, then act
on any prefix lines printed below it.

Components are always resolved live; a failed fetch falls back to the vendored
snapshots in `reference/catalog/`. An `[offline-fallback]` source therefore
always means the read failed — unreachable instance, or a PAT in
`$CATALOG_AUTH_ENV` that is missing, expired, or lacks `read_api` (MIGRATION.md
step 0). Say so; the run continues on the snapshot, but it is not live.

Scripts signal everything else with four prefixes. Surface the line verbatim,
then:

| Prefix | Required action |
|---|---|
| `ADVISORY:` | a newer stable tag exists; report it, change nothing now |
| `DRIFT:` | a configured `image:` differs from the component's; report, never auto-bump it |
| `CONTRACT-DRIFT:` | the component's inputs or reports changed vs `scanners/<runner>.contract`; explain what it affects and ask before scanning |
| `NEEDS-MAPPING:` | the component supports something no runner implements; stop and ask |

`template.yml` is the only machine source of truth. `AGENTS.md` is cached per
component for guidance (offer to summarize) but its prose lags the template —
never derive behaviour from it.

---

## Step 3 — Run the scan

```bash
bash "$SCRIPTS_DIR/run-scan.sh"                        # SCAN_SCOPE=all
bash "$SCRIPTS_DIR/run-scan.sh" --only "$SCAN_SCOPE"   # one category from Step 0
```

run-scan.sh invokes `"$RUNTIME" run` per scanner and `"$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"` before Secret Detection. `resolve-jq.sh` and `container-target.sh` are used internally (`GITLAB_FEATURES=dependency_scanning` for Dependency Scanning). A scanner with no report becomes a HIGH coverage finding (HAS_MISSING_REPORT). Stdout: summary from `normalize.py`. **Branch on exit code AND `coverage_complete` (`scan-coverage.json`), never the code alone**: exit 1 → findings, Step 4; exit 0 + complete → done; exit 0 + incomplete → NOT an all-clear: name each `missing_report` category and why (`evidence.why`), then require a full scan before pushing. `fail_on: none` always exits 0, so its code says nothing about coverage. Flags: `--dry-run`; `--only <category>` (sast|dependency_scanning|secret_detection|container_scanning) — Step 0 scope or Step 5 rescan. `--only` narrows what RUNS, never what is EXPECTED, so a scoped verdict needs the same rule plus a full scan before pushing.

Dependency Scanning produces only an SBOM locally (GitLab matches it server-side behind a `CI_JOB_TOKEN`-only API), so run-scan.sh matches it offline with the Trivy bundled in the container-scanning image. **Those findings and their `fixed_version`s are Trivy's, not GitLab's** — say so: a pre-push signal that will not match the post-push Vulnerability Report exactly. If that match cannot run it becomes a coverage skip.

---

## Step 4 — Review findings

Read `.appsec-results/findings.triaged.json`. Present each finding: severity, name, scanner, location, `verification_status`, `triage_reason`. The model may override a `verification_status` with explicit reasoning. For Secret Detection findings, show only the redacted list from the summary (`Secret Detection findings (redacted)`) — never read raw values from `gl-secret-detection-report.json`.

---

## Step 5 — Fix loop

```bash
bash "$SCRIPTS_DIR/fix-branch.sh" --init
```

Names the branch `appsec/fix-<YYYYMMDD>-<shortsha>`. Ask for approval once before making changes — it will create a new branch. **Skip every finding whose `remediation_status` is `blocked_registry_gap`** — the upgrade is not in the mirror, so attempting it burns an iteration and cannot succeed; it belongs in TRIAGE.md §3b. Loop maximum **5 iterations**: apply fixes → rescan ONLY the affected category (`bash "$SCRIPTS_DIR/run-scan.sh" --only <category>`; for secret findings, rerun only GitLab Secret Detection first) → `bash "$SCRIPTS_DIR/fix-branch.sh" --check-progress <prev_count> <curr_count>` — the two `ACTIONABLE C+H` **counts**, not file paths (exits 1 on cap/no-progress → stop). When the loop ends, run the app's relevant tests. Never push or open an MR without the user explicitly asking. Never rewrite git history.

---

## Step 6 — Generate the triage plan (TRIAGE.md)

After the loop, write `.appsec-results/TRIAGE.md` covering every finding that
was **not** fixed. This is the user's guided companion for GitLab's
Vulnerability Report triage after they push.

Sort every unfixed finding into exactly one section. Only section 4 is a GitLab
dismissal — a dismissal reason anywhere else sends the user to dismiss something
that does not exist in the Vulnerability Report.

```markdown
# AppSec Triage Plan — <APP_NAME> @ <shortsha> (<date>, profile: <profile>)

## 1. Fixed on this branch
| Finding | Severity | Location | What changed |
|---|---|---|---|
(Then: "Verify with <command>". Omit the section if nothing was fixed.)

## 2. Must fix before push — NOT dismissible
Real findings still present. These have no GitLab dismissal reason: the action
is to fix them, or consciously defer with an owner and a date.
### <n>. [<severity>] <title> — <scanner>
- Location: <file:line> · Why not fixed here: <reason> · Owner / by when: <...>

## 3. Coverage gaps — NOT dismissible
A scanner that did not run produces no GitLab vulnerability, so there is nothing
to dismiss. The action is to restore coverage. Copy the `why` text verbatim from
each `APPSEC-REPORT-*` finding — it names the fix.
### <n>. <category> did not run
- What to do: <the finding's evidence.why>

## 3b. Blocked — the fix is not in the mirror — NOT dismissible
Every `remediation_status: blocked_registry_gap` finding. The fix exists upstream
but the internal registry does not carry it, so it could not be applied here.
ONE batched table per kind — this is a single request to the platform team, not
one ask per finding. Omit a table with no rows, the section when both are empty.
| Package | Have | Need | Ecosystem | CVE |
|---|---|---|---|---|

| Base image | Tag to mirror | Dockerfile line | Findings it blocks |
|---|---|---|---|
- What to do: ask the platform team to mirror the packages and images above, then re-run.

**Suggestion only — hardened base images.** Include this block ONLY when
`hardened_repo` actually returned a hit. Nothing was applied and no finding's
status changed. A hardened image is a *different* image — different libc, often
no shell and no package manager, non-root UID — so a human decides whether this
build can take it.
| Current base | Hardened candidate | What to check before swapping |
|---|---|---|

## 4. Dismiss in GitLab
Secure → Vulnerability report → open the finding → **Dismiss vulnerability** →
pick a reason below → paste the justification (a comment is mandatory).
### <n>. [<severity>] <title> — <scanner>
- Location: <file:line or image:layer>
- Dismissal reason: `<one of the five below>`
- Justification (paste-ready): "<2-3 sentences: what was assessed, why this
  reason applies, compensating controls if any, review-by date if temporary>"
```

Section 4 only: use exactly one of GitLab's five dismissal reasons (the only
values it accepts). Never apply them to sections 2 or 3.

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

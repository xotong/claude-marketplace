---
name: appsec-scan
description: >
  Run Chronicle-backed AppSec security scanners locally through Claude Code before
  commit or push. Resolves current GitLab CI component templates at scan time,
  executes supported scanner jobs locally in matching container images, normalizes
  findings, triages likely false positives, and guides Claude Code through local
  branch-based remediation loops until the CI-equivalent gate is clean. Covers
  Fortify SAST/SCA, Parasoft Jtest, Pylint, ESLint, Scantist SCA variants, and
  Prisma Cloud image scanning. Use when the user says: "appsec scan", "appscan",
  "run security scanners", "run Fortify", "run Parasoft", "Scantist scan",
  "Prisma scan", "ESLint security", "Pylint scan", "pre-push security check",
  "CI security pipeline locally", "mirror Chronicle scanners", "container
  security scan", "SCA scan", "SAST scan", or "security before merge". Do NOT
  activate for real Fortify DAST execution, general code review, unit testing, or
  lint-only requests.
---

# AppSec Scan

Run Chronicle security scanner components locally from Claude Code. Claude Code
owns the workflow: resolve scanners, run the helper, inspect structured findings,
explain false positives, edit code when appropriate, and repeat scans. The bundled
Python helper only performs deterministic mechanics.

Use `appsec-dast-sim` separately for OWASP WSTG design-time DAST coverage. Real
Fortify DAST is intentionally excluded from this local shift-left skill.

## Quick Workflow

1. Resolve and run applicable scanners from the project root:

   ```bash
   python3 <skill-dir>/scripts/appsec_harness.py run --gate ci
   ```

2. Read `.appsec-results/findings.triaged.json`.

3. Present the user with:
   - confirmed true positives that can be fixed locally
   - likely false positives with evidence
   - findings that are not locally fixable
   - findings needing human review
   - scanners skipped because required configuration is missing

4. For local remediation, create or reuse an isolated branch:

   ```bash
   python3 <skill-dir>/scripts/appsec_harness.py prepare-branch
   ```

5. Claude Code edits the code, reruns `run --gate ci`, and repeats until the
   CI-equivalent gate is clean, no viable local fixes remain, or five iterations
   have completed.

Do not push the branch or open an MR unless the user explicitly asks.

## Chronicle Resolution

Prefer live Chronicle templates so tenant skill installs do not become stale.
Configure one of these:

```bash
# Best for local platform development
export APPSEC_CHRONICLE_LOCAL_DIR=/path/to/chronicle

# Best for tenant use with raw GitLab URLs
export APPSEC_COMPONENT_RAW_BASE="https://gitlab.example.com/group/chronicle/-/raw/{ref}"

# Alternative: GitLab Repository Files API
export APPSEC_GITLAB_URL="https://gitlab.example.com"
export APPSEC_GITLAB_PROJECT="group/chronicle"
export APPSEC_GITLAB_TOKEN="<token-if-private>"
```

Required for remote template resolution:

```bash
export APPSEC_COMPONENT_REF=<chronicle-commit-sha>
export APPSEC_ALLOWED_COMPONENT_HOSTS=gitlab.example.com
```

Optional:

```bash
export APPSEC_OUTPUT_DIR=.appsec-results
export APPSEC_ALLOWED_IMAGE_REGISTRIES=registry.example.com,docker.io
```

Remote Chronicle templates are fail-closed by default. Use a pinned commit SHA in
`APPSEC_COMPONENT_REF`; `main` or other mutable refs require
`APPSEC_ALLOW_UNPINNED_COMPONENTS=true` and should be limited to controlled
development. If live fetch fails, cached templates under
`${HOME}/.cache/claude-appsec/component-cache/` are used only with
`--allow-stale-cache`.

Scanner container images must use `@sha256:` digests for real runs unless
`APPSEC_ALLOW_MUTABLE_IMAGES=true` is set after accepting image drift risk.
`APPSEC_ALLOWED_IMAGE_REGISTRIES` can restrict scanner images to approved
registries.

## Scanner Coverage

The component registry lives in `references/chronicle-components.yaml`.

Default v1 coverage:
- Fortify Python and JavaScript SAST
- Fortify SCA only when `APPSEC_ENABLE_FORTIFY_SCA=true`
- Parasoft Maven and Gradle
- Pylint and ESLint
- Scantist JS, JS monorepo, Maven, and Gradle
- Prisma Cloud when image inputs are configured

Excluded from v1 local execution:
- Fortify DAST, because it needs a deployed target, scan settings, auth/macro
  state, and long-running API polling
- Kaniko, Podman, release workflow, and SRM helper components
- Legacy Trivy unless a future registry entry explicitly enables it

## Inputs And Secrets

Keep secrets in environment variables. Never write tokens into files or reports.

Common variables:
- `CI_TOKEN`, `ANALYSIS_DOWNLOAD_TOKEN`: Fortify upload/download tokens
- `FORTIFY_SERVER`, `FORTIFY_APPLICATION_NAME`, `FORTIFY_APPLICATION_VERSION`
- `MAVEN_SETTINGS_XML`
- `DEVSECOPS_TOKEN`: Scantist token
- `PRISMA_CLOUD_URL`, `PRISMA_CLOUD_USER`, `PRISMA_CLOUD_PASSWORD`,
  `PRISMA_CLOUD_AUTH`
- `JFROG_REPO`, `JFROG_USER`, `JFROG_PASSWORD`, `JFROG_IMAGE_NAME`,
  `JFROG_IMAGE_TAG`
- `SOURCE_PATH`, `PYLINT_SOURCE`, `PYLINT_OPTIONS`, `ESLINT_CONFIG_FILE`,
  `ESLINT_SOURCE`, `ESLINT_OPTIONS`, `SCANTIST_SOURCE`, `SCANTIST_OPTIONS`

Use `--include-unconfigured` only when debugging template resolution; normal
scans record skipped matching scanners as incomplete coverage so the tenant does
not receive a false clean result.

## Outputs

All output goes under `.appsec-results/` by default:

- `resolved-jobs.json`: resolved scanner jobs
- `scan-coverage.json`: resolved and skipped scanner coverage
- `<component>.sh`: generated Docker runner script
- `<component>.log`: scanner log
- `workspaces/<component>/`: disposable scanner workspace copy
- `reports/<component>/`: collected parseable scanner artifacts
- `findings.normalized.json`: merged finding model
- `findings.triaged.json`: findings with verification status

Read `references/chronicle-harness.md` for helper internals, status meanings,
cache behavior, and remediation loop rules.

## Triage Rules

Classify every finding before proposing code changes:

- `confirmed_true_positive`: concrete vulnerable code, package, image, endpoint,
  or scanner evidence
- `likely_false_positive`: generated/vendor/test/fixture-only code, explicit
  suppression, or insufficient reachability for shipped code
- `not_fixable_locally`: base image, vendor dependency, platform configuration,
  Fortify/Prisma/SRM setup, or infrastructure issue outside this repo
- `needs_human_review`: evidence is insufficient

Never silently suppress likely false positives. Show the evidence to the user.
The CI gate still fails for high or critical likely false positives until the
user explicitly accepts the risk or the finding is remediated.

## Remediation Rules

- Fix only confirmed true positives that are locally fixable.
- Keep work on an `appsec/remediate/...` branch.
- Rerun `python3 <skill-dir>/scripts/appsec_harness.py run --gate ci` after each
  fix cycle.
- Stop after five iterations, a clean gate, no viable fixes, or the same finding
  surviving two attempted fixes.
- Summarize final status with branch name, changed files, scan command, raw
  report paths, remaining findings, and likely false positives.

## Helper Commands

```bash
python3 <skill-dir>/scripts/appsec_harness.py resolve
python3 <skill-dir>/scripts/appsec_harness.py run --gate ci
python3 <skill-dir>/scripts/appsec_harness.py run --dry-run --include-unconfigured
python3 <skill-dir>/scripts/appsec_harness.py run --gate ci --allow-stale-cache
python3 <skill-dir>/scripts/appsec_harness.py normalize --results-dir .appsec-results/reports
python3 <skill-dir>/scripts/appsec_harness.py triage --gate ci
python3 <skill-dir>/scripts/appsec_harness.py prepare-branch
```

Replace `<skill-dir>` with the installed `appsec-scan` skill directory.

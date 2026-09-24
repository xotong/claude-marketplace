---
id: secret-detection
category: secret-detection
summary: Scans commits for hardcoded secrets/credentials using GitLab's native Secret Detection analyzer (Gitleaks-based).
---

## When to use

- You need to catch committed secrets/credentials on every pipeline.
- You need a one-off scan of the full git history (set `historic_scan: true`).

## When NOT to use

- You are looking for code vulnerabilities, not leaked credentials. Use a SAST component instead.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `stage` | no | `test` | Pipeline stage |
| `enable_mr_pipelines` | no | `false` | If `true`, run on merge request pipelines instead of duplicate branch pipelines |
| `historic_scan` | no | `false` | `false` scans incoming commits only. `true` scans all commits ever |
| `tags` | no | `""` | Runner tags for the job |

## Jobs created

- One job named `secret_detection`, with `allow_failure: true`.
- The job clones with `GIT_DEPTH: "50"`. For `historic_scan: true`, override `GIT_DEPTH: "0"` on the job (see Usage) so all commits are available.
- With `enable_mr_pipelines: false` (default): runs on branch pipelines only.
- With `enable_mr_pipelines: true`: runs on MR, branch, scheduled, web, and API pipelines; skips the duplicate branch pipeline when an MR is open; never runs on tag pipelines.

## Outputs

- `gl-secret-detection-report.json` — feeds GitLab's `secret_detection` security report.

## Required CI/CD variables

None required. Optional tuning via job-level variables (see Usage): `SECRET_DETECTION_EXCLUDED_PATHS`, `SECRET_DETECTION_LOG_OPTIONS`.

## Usage

Use a release tag (for example `1.0.0`) or `~latest` for the newest release.

```yaml
include:
  - component: $CI_SERVER_FQDN/ci-components/secret-detection/secret-detection@1.0.0
    inputs:
      stage: security-scans
      historic_scan: true
      tags: medium

# Optional overrides on the created job
secret_detection:
  variables:
    GIT_DEPTH: "0"  # full clone, needed for historic_scan
    SECRET_DETECTION_EXCLUDED_PATHS: "spec,docs,test"
```

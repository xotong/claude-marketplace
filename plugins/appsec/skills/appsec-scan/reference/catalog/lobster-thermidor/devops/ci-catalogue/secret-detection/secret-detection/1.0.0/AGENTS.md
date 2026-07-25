---
id: secret-detection
category: secret-detection
summary: Scans commits for hardcoded secrets/credentials using GitLab's native Secret Detection analyzer (Gitleaks-based).
---

## When to use

- Need to catch committed secrets/credentials, on every pipeline or as a one-off historic scan.

## When NOT to use

- Looking for code vulnerabilities rather than leaked credentials — use a SAST component instead.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `stage` | no | `test` | Pipeline stage |
| `image_tag` | no | `7` | Version of the `secrets` analyzer image |
| `enable_mr_pipelines` | no | `false` | Run on merge request pipelines in addition to branch pipelines |
| `tags` | no | — | Custom runner tags |

## Required CI/CD variables

None required by default. Optional tuning variables: `SECRET_DETECTION_EXCLUDED_PATHS`, `SECRET_DETECTION_HISTORIC_SCAN`, `SECRET_DETECTION_LOG_OPTIONS`.

## Usage

```yaml
include:
  - component: $CI_SERVER_FQDN/devops/ci-catalogue/secret-detection/secret-detection@main
    inputs:
      stage: security-scans
      tags: medium

secret_detection:
  variables:
    SECRET_DETECTION_EXCLUDED_PATHS: "spec,docs,test"
    SECRET_DETECTION_HISTORIC_SCAN: "true"
```

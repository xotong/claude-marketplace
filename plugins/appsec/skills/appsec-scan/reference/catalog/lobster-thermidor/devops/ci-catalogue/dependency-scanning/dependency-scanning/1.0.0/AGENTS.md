---
id: dependency-scanning
category: sca
summary: Software Composition Analysis of project dependencies (Python, JavaScript, Maven, Gradle) using GitLab's native Dependency Scanning analyzer.
---

## When to use

- Need open-source dependency vulnerability scanning that reports into GitLab's native Security Dashboard rather than SRM.

## When NOT to use

- Need results in SRM, or need license-compliance policy checks — use `scantist-sca` instead.
- Need scanning of your own source code, not third-party dependencies — use a SAST component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `job-name` | no | `dependency-scanning` | Job name |
| `stage` | no | `test` | Pipeline stage |
| `allow_failure` | no | `true` | Allow job to fail without blocking pipeline |
| `language` | yes | — | `maven` \| `gradle` \| `python` \| `javascript` |
| `resolution_job_registry` | no | — | Image registry for the dependency-resolution job |
| `resolution_job_variant` | no | `openjdk17` | `openjdk17` \| `openjdk21` |
| `analyzer_log_level` | no | `info` | `fatal` \| `error` \| `warn` \| `info` \| `debug` |

## Required CI/CD variables

None beyond standard registry access for `resolution_job_registry`.

## Usage

```yaml
include:
  - component: $CI_SERVER_FQDN/devops/ci-catalogue/dependency-scanning/dependency-scanning@<VERSION>
    inputs:
      stage: test
      language: maven
```

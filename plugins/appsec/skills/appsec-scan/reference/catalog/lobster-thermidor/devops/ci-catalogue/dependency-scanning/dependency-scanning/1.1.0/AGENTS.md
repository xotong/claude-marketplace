---
id: dependency-scanning
category: sca
summary: Software Composition Analysis of project dependencies (Maven, Gradle, Python, JavaScript) using GitLab's native Dependency Scanning analyzer.
---

## When to use

- You need open-source dependency vulnerability scanning that reports into GitLab's Security Dashboard (not SRM).
- The project language is `maven`, `gradle`, `python`, or `javascript`.

## When NOT to use

- You need results in SRM, or license-compliance policy checks. Use `scantist-sca` instead.
- You need scanning of your own source code, not third-party dependencies. Use a SAST component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `language` | yes | — | One of: `maven`, `gradle`, `python`, `javascript` |
| `job-name` | no | `dependency-scanning` | Base name for the created jobs |
| `stage` | no | `test` | Stage of the main scanning job |
| `allow_failure` | no | `true` | Applies to the main job only. If `true`, a failed scan does not block the pipeline. Resolution jobs always allow failure |
| `analyzer_log_level` | no | `info` | One of: `fatal`, `error`, `warn`, `info`, `debug` |
| `resolution_job_registry` | no | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/gitlab-scanners` | Image registry for the resolution job |
| `resolution_job_variant` | no | `openjdk17` | JDK for resolution: `openjdk17` or `openjdk21` |
| `resolution_job_tag` | no | `toolbox:1.0.0` | Image tag for the resolution job |
| `maven-setting-path` | no | `settings.xml` | Maven settings file (maven only) |
| `pip-index-url` | no | `https://pypi.org/simple/` | pip index URL (python only) |
| `python-version` | no | `3.12` | Python version (python only) |

## Jobs created

- `<job-name>` — the main scanning job, in `stage`. Runs for all four languages.
- `<job-name>-maven`, `<job-name>-gradle`, or `<job-name>-python` — a dependency-resolution job in the `.pre` stage. Only the job matching `language` runs. `javascript` has no resolution job.
- The gradle resolution job runs only on branch pipelines, and only if the repo contains a `gradlew` wrapper. Add one if missing.

## Outputs

- `gl-dependency-scanning-report.json` — feeds GitLab's `dependency_scanning` security report.
- `gl-sbom-*.cdx.json` — CycloneDX SBOM, feeds GitLab's `cyclonedx` report.
- Resolution job artifacts (kept for debugging): `maven.graph.json`, `gradle.graph.txt`, or `pipcompile.lock.txt`.

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `ARTIFACTORY_USERNAME` | `language: gradle` and packages are pulled from Artifactory |
| `ARTIFACTORY_PASSWORD` | `language: gradle` and packages are pulled from Artifactory |

## Usage

Use a release tag (for example `1.0.0`) or `~latest` for the newest release.

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning@1.0.0
    inputs:
      stage: test
      language: maven
```

---
id: fortify-sast
category: sast
summary: Fortify SCA static analysis of source code (Maven, Gradle, Python, JavaScript), with results uploaded to the GitLab Vulnerability Dashboard and optionally to SRM.
---

## When to use

- You need Fortify SAST scanning of your own source code.
- The project language is `maven`, `gradle`, `python`, or `javascript`.
- You need results in the GitLab Vulnerability Dashboard, SRM, or both.

## When NOT to use

- You are scanning third-party dependencies, not your own code. Use `dependency-scanning` or `scantist-sca`.
- You are scanning a container image. Use a container-scanning component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `language` | yes* | `javascript` | One of: `maven`, `gradle`, `python`, `javascript`. *Always set this explicitly |
| `source-path` | no | `src` | Path of the source code to scan. Use `.` for the repo root |
| `job-name` | no | `fortify-scan` | Base name for the created jobs |
| `stage` | no | `sast` | Pipeline stage |
| `allow-failure` | no | `true` | If `true`, a failed scan does not block the pipeline |
| `downloaded-scan-report-name` | no | `scan.fpr` | Filename of the Fortify FPR report |
| `upload-srm-option` | no | `"false"` | Set to `"true"` to also upload results to SRM |
| `variant` | no | `jdk17-review` | JDK for compilation: `jdk17-review` or `jdk21-review` |
| `registry` | no | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/` | Scanner image registry |
| `image` | no | `fortify-sca` | Scanner image name |
| `image-tag` | no | `25.2.0` | Scanner image tag |
| `srm-branch` | no | `$CI_COMMIT_REF_NAME` | Branch name created in SRM |
| `git-branch-name` | no | `$CI_COMMIT_REF_NAME` | Git branch used for SRM analysis. SRM does not support tags as branch names |
| `maven-setting-path` | no | `settings.xml` | Maven settings file (maven only). The file must exist in the repo or the maven build fails |
| `pip-index-url` | no | `jfrog.com/artifactory/api/pypi/pypi/simple` | pip index URL (python only) |
| `python-version` | no | `3.12` | Python version (python only) |

## Jobs created

- `<job-name>-<language>` — the Fortify scan. Only the job matching `language` runs. It **fails when critical or high severity issues are found** (with `allow-failure: true` the pipeline still continues).
- `<job-name>-<language>-gitlab-upload` — converts the FPR report and uploads it to the GitLab Vulnerability Dashboard.
- `<job-name>-scan-upload` — uploads the report to SRM. Comes from the included `srm-report-upload` component. Controlled by `upload-srm-option`.
- Gradle projects must have a working `gradlew` wrapper in the repo.
- If a `filter_list.txt` file exists in the repo root, the scan applies it as a Fortify filter file, which changes reported results.

## Outputs

- `gl-sast-report.json` — feeds GitLab's `sast` security report.
- `scan.fpr` — Fortify Project Report.
- `fortify.html`, `fortify.pdf`, `fortify.xml` — Developer Workbook reports, kept as artifacts.

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `ARTIFACTORY_USER` | `language: gradle` and the build pulls packages from Artifactory |
| `ARTIFACTORY_PASSWORD` | `language: gradle` and the build pulls packages from Artifactory |
| `SRM_API_KEY` | `upload-srm-option: "true"`. Copy the whole key, including the `api-key:` prefix |
| `SRM_PROJECT_ID` | `upload-srm-option: "true"`. The numeric id in the SRM project URL, e.g. `20` in `https://srm.com/srm/projects/20` |

## Usage

Use a release tag (for example `25.2.0`) or `~latest` for the newest release.

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
    inputs:
      stage: sast
      language: maven
      source-path: .
      maven-setting-path: settings.xml
      variant: jdk17-review
```

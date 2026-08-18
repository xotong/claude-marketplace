---
id: fortify-sast
category: sast
summary: Fortify SCA static analysis of source code (Maven, Gradle, Python, JavaScript, Go), with results uploaded to the GitLab Vulnerability Dashboard and optionally to SRM.
---

## When to use

- You need Fortify SAST scanning of your own source code.
- The project language is `maven`, `gradle`, `python`, `javascript`, or `go`.
- You need results in the GitLab Vulnerability Dashboard, SRM, or both.

## When NOT to use

- You are scanning third-party dependencies, not your own code. Use `dependency-scanning` or `scantist-sca`.
- You are scanning a container image. Use a container-scanning component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `language` | yes* | `javascript` | One of: `maven`, `gradle`, `python`, `javascript`, `go`. *Always set this explicitly |
| `source-path` | no | `src` | Path of the source code to scan. Use `.` for the repo root |
| `job-name` | no | `fortify-scan` | Base name for the created jobs |
| `stage` | no | `sast` | Pipeline stage |
| `allow-failure` | no | `true` | If `true`, a failed scan does not block the pipeline |
| `downloaded-scan-report-name` | no | `scan.fpr` | Filename of the Fortify FPR report |
| `upload-srm-option` | no | `"false"` | Set to `"true"` to also upload results to SRM |
| `variant` | no | `jdk17-review` | JDK for compilation: `jdk17-review` or `jdk21-review` |
| `registry` | no | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/` | Scanner image registry |
| `image` | no | `fortify-sca` | Scanner image name |
| `image-tag` | no | `25.2.0` | Scanner image tag |
| `srm-branch` | no | `$CI_COMMIT_REF_NAME` | Branch name created in SRM |
| `git-branch-name` | no | `$CI_COMMIT_REF_NAME` | Git branch used for SRM analysis. SRM does not support tags as branch names |
| `maven-setting-path` | no | `settings.xml` | Maven settings file (maven only). The file must exist in the repo or the maven build fails |
| `pip-index-url` | no | `https://pypi.org/simple/` | Python package index (python only, `full` mode). Applied as `UV_DEFAULT_INDEX` and `PIP_INDEX_URL`. Must include the scheme |
| `translation-mode` | no | `normal` | `normal` translates only the project's own code; `full` also follows imports into installed dependencies (python only). **`full` can take hours and may not finish** — see *Python translation mode* below |
| `python-version` | no | `3.12` | Python version (python only). One of `3.10`–`3.14` |
| `python-template-dirs` | no | *(empty)* | Colon-separated Django/Jinja2 template directories, relative to the repo root (python only). Set this if the scan logs *unable to discover any Django/Jinja2 template directories* |
| `uv-version` | no | `0.11.28` | Pinned uv version to install (python only) |
| `uv-installer-base` | no | `https://releases.astral.sh/github/uv/releases/download` | Where the uv installer script is fetched from. Point at an internal JFrog mirror for air-gapped runners (python only) |
| `uv-python-install-mirror` | no | `https://github.com/astral-sh/python-build-standalone/releases/download` | Where uv downloads the managed Python build from. Point at an internal JFrog mirror for air-gapped runners (python only) |

## Jobs created

- `<job-name>-<language>` — the Fortify scan. Only the job matching `language` runs. It converts the FPR to `gl-sast-report.json` and uploads it as the `sast` report. It does **not** fail on critical or high findings; that gate was removed and gating now belongs to GitLab security policies.
- `<job-name>-scan-upload` — uploads the report to SRM. Comes from the included `srm-report-upload` component. Controlled by `upload-srm-option`.
- Gradle projects must have a working `gradlew` wrapper in the repo.
- If a `filter_list.txt` file exists in the repo root, the scan applies it as a Fortify filter file, which changes reported results.

## Python environment

What the python job does depends on `translation-mode`.

In **`normal`** (the default) no dependencies are installed and only the interpreter's
standard-library directory goes on `-python-path`. Third-party imports log as warnings. This is the
mode to use in CI.

In **`full`** the job builds a virtualenv with `uv` and puts the venv's `site-packages` on
`-python-path` as well. `uv` and the managed Python interpreter are fetched from the public internet
by default; for air-gapped runners, point `uv-installer-base` and `uv-python-install-mirror` at
internal JFrog mirrors.

Either way the interpreter's standard-library directory is on `-python-path`. SCA bundles only a
subset of the stdlib and ignores `PYTHONPATH`, so without it, imports such as `logging`, `json` and
`textwrap` resolve as unknown and taint through them is lost.

## Python translation mode

SCA translates whatever `-python-path` resolves; there is no resolve-without-translate mode for
Python. So `full` does not merely *read* dependencies, it translates the whole transitive closure.

Measured on a 230-package langchain service:

| mode | result |
| --- | --- |
| `normal` | 64s, all 21 project files translated, report produced |
| `full` | exceeded a 3h job timeout having translated 6,100 dependency files and **1 of 21** project files, producing no report |

A 60-package Django service completes `full` in ~4 minutes and gains genuine signal — `django` and
`jwt` resolve, so taint traces through request handling, the ORM and auth. Pick per source, not per
platform.

Every run prints `Translated N of M .py file(s) under <source-path>`. If N is far below M, the scan
spent its budget inside `site-packages`; switch to `normal`.

`-exclude '**/site-packages/**'` and `-Dcom.fortify.sca.follow.imports=false` do **not** work for
Python — both were measured and are inert (the `-exclude` run translated *more* site-packages files
than the baseline). They are documented for JavaScript/TypeScript only.

Template scanning is opt-in via `python-template-dirs`. SCA autodiscovers templates only in the
project root and does **not** read Django's `TEMPLATE_DIRS` setting, so an app whose templates live
elsewhere gets no template coverage until the directories are named.

`pip-index-url` is exported as `UV_DEFAULT_INDEX` and `PIP_INDEX_URL` in the job's `variables:`, so
it applies to every uv invocation. `UV_INDEX_URL` is deliberately not set: it is the deprecated
spelling and makes `uv` warn on install.

**Precedence caveat:** a project- or group-level CI/CD variable named `PIP_INDEX_URL` or
`UV_DEFAULT_INDEX` overrides the job `variables:` set from `pip-index-url`, and the
input is then silently ignored.

## Outputs

- `gl-sast-report.json` — feeds GitLab's `sast` security report.
- `scan.fpr` — Fortify Project Report.
- `fortify.html`, `fortify.pdf`, `fortify.xml` — Developer Workbook reports, kept as artifacts.

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `ARTIFACTORY_USER` | `language: gradle` and the build pulls packages from Artifactory. `ARTIFACTORY_USERNAME` is accepted as a fallback, for parity with `dependency-scanning` |
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

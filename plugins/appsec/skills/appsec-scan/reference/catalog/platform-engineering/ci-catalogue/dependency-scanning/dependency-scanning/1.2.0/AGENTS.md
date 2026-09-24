---
id: dependency-scanning
category: sca
summary: Software Composition Analysis of project dependencies (Maven, Gradle, Python, JavaScript, Go) using GitLab's native Dependency Scanning analyzer.
---

## When to use

- You need open-source dependency vulnerability scanning that reports into GitLab's Security Dashboard (not SRM).
- The project language is `maven`, `gradle`, `python`, `javascript`, or `go`.

## When NOT to use

- You need results in SRM, or license-compliance policy checks. Use `scantist-sca` instead.
- You need scanning of your own source code, not third-party dependencies. Use a SAST component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `language` | yes | — | One of: `maven`, `gradle`, `python`, `javascript`, `go` |
| `job-name` | no | `dependency-scanning` | Base name for the created jobs |
| `stage` | no | `test` | Stage of the main scanning job |
| `allow_failure` | no | `true` | Applies to the main job only. If `true`, a failed scan does not block the pipeline. Resolution jobs always allow failure |
| `analyzer_log_level` | no | `info` | One of: `fatal`, `error`, `warn`, `info`, `debug` |
| `resolution_job_registry` | no | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/gitlab-scanners` | Image registry for the resolution job |
| `resolution_job_variant` | no | `openjdk17` | JDK for resolution: `openjdk17` or `openjdk21` |
| `resolution_job_tag` | no | `toolbox:1.0.0` | Image tag for the resolution job |
| `maven-setting-path` | no | `settings.xml` | Maven settings file (maven only) |
| `pip-index-url` | no | `https://pypi.org/simple/` | Python package index (python only). Applied as `UV_DEFAULT_INDEX`, `UV_INDEX_URL` and `PIP_INDEX_URL` on both the main job and the python resolution job |
| `python-version` | no | `3.12` | Python version (python only) |
| `uv-version` | no | `0.11.28` | Pinned uv version to install (python only) |
| `uv-installer-base` | no | `https://releases.astral.sh/github/uv/releases/download` | Where the uv installer script is fetched from. Point at an internal JFrog mirror for air-gapped runners (python only) |
| `uv-python-install-mirror` | no | `https://github.com/astral-sh/python-build-standalone/releases/download` | Where uv downloads the managed Python build from. Point at an internal JFrog mirror for air-gapped runners (python only) |

## Jobs created

- `<job-name>` — the main scanning job, in `stage`. Runs for every supported language.
- `<job-name>-maven`, `<job-name>-gradle`, or `<job-name>-python` — a dependency-resolution job in the `.pre` stage. Only the job matching `language` runs. `javascript` and `go` have no resolution job.
- The gradle resolution job runs only on branch pipelines, and only if the repo contains a `gradlew` wrapper. Add one if missing.

## Python dependency resolution

**uv is the authoritative resolver for python.** The `-python` job replaces the analyzer's generated
`dependency_resolution.sh` with a uv-based one, so `pipcompile.lock.txt` is produced by
`uv pip compile`, not by `pip-compile`.

The analyzer's main job can still fall back to its own stock `pip-compile` path, and that path reads
a different variable than uv does. `pip-index-url` is therefore exported in three spellings —
`UV_DEFAULT_INDEX` (current uv), `UV_INDEX_URL` (older uv), `PIP_INDEX_URL` (pip / pip-compile) — on
both jobs, so whichever resolver runs reads the same index.

No index is passed as a command-line flag. `UV_DEFAULT_INDEX` silently overrides `--index-url` with
no warning, so a flag would read as authoritative without being so.

`uv` and the managed Python interpreter are fetched from the public internet by default. For
air-gapped runners, point `uv-installer-base` and `uv-python-install-mirror` at internal JFrog
mirrors; nothing else needs changing.

The resolution job is `allow_failure: true`. If `uv pip compile` fails for a directory — most often
because that project's own requirements are unsatisfiable — no `pipcompile.lock.txt` is written for
it, the analyzer falls back to parsing the plain manifest, and that service's SBOM silently drops to
**direct dependencies only** while the pipeline stays green. The analyzer logs
`MANIFEST FALLBACK` and `Only direct dependencies will be detected`; treat those as a real coverage
gap, not noise.

**Precedence caveat:** a project- or group-level CI/CD variable named `PIP_INDEX_URL`,
`UV_DEFAULT_INDEX` or `UV_INDEX_URL` overrides the job `variables:` set from `pip-index-url`, and the
input is then silently ignored.

## One include per project, not per language

The main `<job-name>` job is **language-agnostic** — it runs `/analyzer run`, which walks the
whole repo and builds an SBOM for every manifest it finds, regardless of the `language` input.
`language` only selects which dependency-*resolution* job runs in `.pre`.

So including this component once per language does **not** split the work: each include produces
another full scan of the entire repo and another duplicate set of `gl-sbom-*.cdx.json` reports in
the same pipeline. Verified: three includes (`python`, `gradle`, `javascript`) each generated the
same 6 SBOMs and the same 354 findings.

Include the component **once**, with `language` set to whichever language needs dependency
resolution. If several languages need resolution, that is the one case for multiple includes —
set a distinct `job-name` for each and accept the duplicate main jobs.

## Outputs

- `gl-dependency-scanning-report.json` — feeds GitLab's `dependency_scanning` security report.
- `gl-sbom-*.cdx.json` — CycloneDX SBOM, feeds GitLab's `cyclonedx` report.
- Resolution job artifacts (kept for debugging): `maven.graph.json`, `gradle.graph.txt`, or `pipcompile.lock.txt`.

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `ARTIFACTORY_USERNAME` | `language: gradle` and packages are pulled from Artifactory. `ARTIFACTORY_USER` is accepted as a fallback, for parity with `fortify-sast` |
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

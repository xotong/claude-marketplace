---
id: container-scanning
category: container-scan
summary: Static vulnerability scan of a container image using GitLab's native Container Scanning analyzer, with optional JFrog Artifactory authentication.
---

## When to use

- You need container image scanning that reports into GitLab's Security Dashboard (not SRM).
- The image is pushed to a registry (for example JFrog/Artifactory) and reachable from the runner.

## When NOT to use

- You need results in SRM instead of GitLab's dashboard. Use `trivy`, `acs`, or `prisma-cloud` instead.
- You are scanning source code, not a built image. Use a SAST or dependency-scanning component.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `stage` | no | `security-scans` | Pipeline stage |
| `job_name` | no | `container_scanning` | Name of the created job |
| `cs_image` | no | `artifactory.com:$CI_APPLICATION_TAG` | Full image reference to scan |
| `cs_dockerfile_path` | no | `Dockerfile` | Dockerfile path, used for remediation suggestions |
| `dependencies` | no | `[]` | CI jobs this job depends on |
| `git_strategy` | no | `fetch` | `fetch` enables auto-remediation/allowlisting; `none` disables repo checkout |
| `enable_mr_pipelines` | no | `true` | Also run in merge request pipelines |
| `jfrog_registry` | no | `""` | JFrog registry URL. If empty, it is extracted from `cs_image` |
| `tags` | no | `""` | One runner tag. Set it if your runners are tagged; the default leaves an empty tag |

## Jobs created

- One job, named by `job_name` (default `container_scanning`), with `allow_failure: true`.
- With `enable_mr_pipelines: true`: runs in MR pipelines, and skips the duplicate branch pipeline when an MR is open.
- With `enable_mr_pipelines: false`: runs only in branch pipelines, even when an MR is open.
- In FIPS mode (`$CI_GITLAB_FIPS_MODE == "true"`) the analyzer automatically uses the `-fips` image variant.

## Outputs

- `gl-container-scanning-report.json` — feeds GitLab's `container_scanning` security report.
- `gl-sbom-*.cdx.json` — CycloneDX SBOM, feeds GitLab's `cyclonedx` report.

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `JFROG_TOKEN` | The image registry requires authentication. The job logs in to `jfrog_registry` (or the registry parsed from `cs_image`); the token is used as the Docker username with an empty password. |

## Usage

Use a release tag (for example `1.0.0`) or `~latest` for the newest release.

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning@1.0.0
    inputs:
      stage: security-scans
      cs_image: docker-yourProj.artifactory.com/my-image:latest
      jfrog_registry: docker-yourProj.artifactory.com
```

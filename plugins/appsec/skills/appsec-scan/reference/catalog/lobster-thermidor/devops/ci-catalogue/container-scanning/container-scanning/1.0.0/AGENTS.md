---
id: container-scanning
category: container-scan
summary: Static vulnerability scan of a container image using GitLab's native Container Scanning analyzer.
---

## When to use

- Need container image scanning that reports into GitLab's native Security Dashboard rather than SRM.
- Image is reachable at a JFrog/Artifactory URL.

## When NOT to use

- Need results in SRM rather than GitLab's dashboard — use `trivy`, `acs`, or `prisma-cloud` instead.
- Scanning source code, not an image.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `stage` | no | `security-scans` | Pipeline stage |
| `cs_image` | no | `artifactory.com:$CI_APPLICATION_TAG` | Image to analyze |
| `cs_dockerfile_path` | no | `Dockerfile` | Path to Dockerfile for remediation suggestions |
| `dependencies` | no | `[]` | CI jobs this job depends on |
| `git_strategy` | no | `none` | Use `fetch` to enable auto-remediation/allowlisting |
| `job_name` | no | `container_scanning` | Job name |
| `enable_mr_pipelines` | no | `true` | Run in merge request pipelines |
| `jfrog_registry` | no | — | JFrog registry URL (extracted from `cs_image` if omitted) |
| `tags` | no | — | Custom runner tags |

## Required CI/CD variables

| Variable | Required when |
|---|---|
| `JFROG_TOKEN` | registry requires authentication |

## Usage

```yaml
include:
  - component: $CI_SERVER_FQDN/devops/ci-catalogue/container-scanning/container-scanning@<VERSION>
    inputs:
      stage: static_scans
      cs_image: docker-yourProj.artifactory.com/my-image:latest
      jfrog_registry: docker-yourProj.artifactory.com
```

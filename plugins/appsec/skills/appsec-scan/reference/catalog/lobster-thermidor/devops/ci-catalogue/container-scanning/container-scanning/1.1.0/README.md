<!-- Vendored snapshot: fetched 2026-08-16 from https://gitlab.com CI/CD Catalog (component tag 1.1.0, commit e35c9f26) -->
# Container Scanning

This is a version of Gitlab Container Scan v5.2.0  prepared for our platform

Gitlab Container Scan is basically gitlab's native image scanning tool

How it works:
1. you tell the component where your image is (jfrog link)
2. the component will download the image and inspect it for vulnerabilities

It is a static scan. No containers are actually run

## Usage

Use this component to enable image scanning in your project.
You should add this component to an existing `.gitlab-ci.yml` file by using the `include:`
keyword.

```yaml
include:
  - component: $CI_SERVER_FQDN/devops/ci-catalogue/container-scanning/container-scanning@<VERSION>
    inputs:
      stage: static_scans
      cs_image: myregistry.artifactory.com/my-image:latest
   
```

### With JFrog Artifactory Credentials

If your JFrog Artifactory registry requires authentication, store your access token as a CI/CD variable named `JFROG_TOKEN`:

```yaml
include:
  - component: $CI_SERVER_FQDN/devops/ci-catalogue/container-scanning/container-scanning@<VERSION>
    inputs:
      stage: static_scans
      cs_image: docker-yourProj.artifactory.com/my-image:latest
      jfrog_registry: docker-yourProj.artifactory.com
```

> The `JFROG_TOKEN` CI/CD variable should contain your JFrog access token

| Input | Default | Description |
|-------|---------|-------------|
| `stage` | `security-scans` | The CI stage for the job |
| `cs_image` | `artifactory.com:$CI_APPLICATION_TAG` | The image to analyze (e.g., JFrog URL) |
| `cs_dockerfile_path` | `Dockerfile` | Path to the Dockerfile for generating remediations |
| `dependencies` | `[]` | List of CI jobs that container scanning depends on |
| `git_strategy` | `none` | Git strategy for the job; use `fetch` to enable auto-remediation or vulnerability allowlisting |
| `job_name` | `container_scanning` | The name to give the container scanning job |
| `enable_mr_pipelines` | `true` | Whether the job should run in merge request pipelines |
| `jfrog_registry` | `` | JFrog Artifactory registry URL (e.g., docker-yourProj.artifactory.com). If not provided, will be extracted from cs_image. |
| `tags` | ""     | Pick your runner! |

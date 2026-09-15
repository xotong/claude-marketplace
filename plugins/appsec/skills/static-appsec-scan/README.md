# static-appsec-scan

Run static security scans locally using `glci` — the same scanners as GitLab CI.

## Scanners

| Category | What it checks | Component (default) |
|---|---|---|
| **SAST** | Static Application Security Testing (code vulnerabilities) | `pipeline-component/fortify-sast/fortify-sast@main` |
| **Secret Detection** | Hardcoded credentials, API keys | `pipeline-component/secret-detection/secret-detection@main` |
| **Container Scanning** | OS/package CVEs in container images | `pipeline-component/container-scanning/container-scanning@main` |
| **SCA** | Software Composition Analysis (dependency vulnerabilities) | `scan-and-upload-sbom.sh` |

**Note:** This skill does **NOT** perform dependency scanning (SCA/SBOM) via GitLab CI component. It uses a custom `scan-and-upload-sbom.sh` script that uploads to GitLab for remote analysis.

### Multi-Dockerfile Container Scanning

When multiple Dockerfiles are detected in your project, the script:
1. Builds and scans each Dockerfile separately
2. Stores individual reports in per-Dockerfile subdirectories
3. Merges all findings into a combined report
4. Displays an aggregated summary with total vulnerabilities across all images

This ensures comprehensive coverage of all container images in your project.

## Auto-Generated Pipeline

### No pipeline exists
When you run a full scan (`--scope all`) without an existing `.gitlab-ci.yml`, the skill **automatically generates** a pipeline using the CI/CD components from `config/scanner-preferences.yaml`. No manual setup required — just provide the language and source path.

### Pipeline exists but missing components
If an existing `.gitlab-ci.yml` is found but is missing scan components:
1. A timestamped backup is created (`.gitlab-ci.yml.bak.<timestamp>`)
2. Missing components are automatically added to the `include:` section
3. The updated pipeline is displayed for review

This ensures your pipeline always has all required scanners without manual editing.

## Quick Start

```bash
# Full security scan (all 3 static scanners)
glci run --stage scans

# Run specific scanner
glci run fortify-sast           # SAST only
glci run secret-detection       # Secret detection only
glci run container-scanning     # Container scanning only
```

## Configuration

Edit `config/scanner-preferences.yaml` to configure:
- GitLab instance URL
- Authentication token
- Docker images to pre-pull
- Scanner component versions

## Prerequisites

- `glci` binary (GitLab CI local runner)
- Docker daemon
- Required images: `alpine:latest`, `gitlab/gitlab-runner:latest`, `gitlab-runner-helper`

Run `./scripts/check-prereqs.sh` to verify your setup.

## Usage

```bash
# Simple: Run all scans (auto-checks prereqs, loads config, generates pipeline)
./scripts/run-glci-scan.sh --language javascript --download

# Run specific scanner
./scripts/run-glci-scan.sh --only sast --language javascript
./scripts/run-glci-scan.sh --only secret
./scripts/run-glci-scan.sh --only container

# Manual step-by-step
./scripts/check-prereqs.sh --download   # Check/install prerequisites
./scripts/generate-pipeline.sh --language javascript  # Generate pipeline
./scripts/run-glci-scan.sh              # Run scans
```

## Difference from local-appsec-scan

| Feature | static-appsec-scan | local-appsec-scan |
|---|---|---|
| SAST | ✅ | ✅ |
| Secret Detection | ✅ | ✅ |
| Container Scanning | ✅ | ✅ |
| Dependency Scanning | ❌ | ✅ |

Use `static-appsec-scan` when you want fast static analysis without dependency scanning overhead.

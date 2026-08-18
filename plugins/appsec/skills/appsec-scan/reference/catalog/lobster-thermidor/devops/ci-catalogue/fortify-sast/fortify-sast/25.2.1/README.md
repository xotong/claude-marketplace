<!-- Vendored snapshot: fetched 2026-08-19 from https://gitlab.com CI/CD Catalog (component tag 25.2.1, commit b4eb953e) -->
# Fortify SAST Pipeline Component

A GitLab CI/CD pipeline component for integrating Fortify Static Application Security Testing (SAST) into your software development workflow. This component provides automated security scanning for multiple programming languages and integrates with both Gitlab vulnerability dashboard and Software Risk Measurement (SRM) for vulnerability tracking.

## Features

- **Multi-language Support**: Scan projects written in Python, JavaScript, Maven, or Gradle
- **Automated Security Scanning**: Integrates Fortify SCA for static code analysis
- **SRM Integration**: Optional upload of scan reports to Software Risk Measurement (SRM)
- **Gitlab vulnerability Dashboard Support**: Automatic upload of scan reportss to Gitlab Vulnerability dashboard
- **Configurable Job Settings**: Customize job names, stages, source paths, and failure behavior
- **Multiple Report Formats**: Generates HTML, PDF, and XML reports
- **Critical/High Issue Reporting**: Surfaces critical and high severity issues in the report. The job does **not** fail on them — that gate was removed, and blocking belongs to GitLab security policies

## Usage

### Basic Usage

Include this component in your `.gitlab-ci.yml` file:

```yaml
# To select the latest release of the component:
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest 

# To select the component based on specific tag:
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@<VERSION>
```

To configure `inputs` :

### Maven Project

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
    inputs: 
      stage: scans
      language: maven
      source-path: .
      maven-setting-path: maven_setting.xml
      variant: jdk17-review # For Java 17
```

### Gradle Project 

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
    inputs: 
      stage: scans
      language: gradle
      source-path: .
      variant: jdk21-review # For Java 21
```

### JavaScript Project
```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
    inputs: 
      stage: scans
      language: javascript
      source-path: .
```

### Python Project

```yaml
include:
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast@~latest
    inputs: 
      stage: scans
      language: python
      source-path: .
      python-version: "3.11"      # match the interpreter your app actually ships
      translation-mode: normal    # default; see below before choosing full

```

#### Python translation mode :hourglass_flowing_sand:

SCA translates whatever `-python-path` resolves, and there is no
resolve-without-translate mode for Python. So this is an either/or, not a dial:

| mode | what it translates | cost |
| --- | --- | --- |
| `normal` (default) | your project's code only; dependencies are neither installed nor placed on `-python-path` | seconds to minutes |
| `full` | also follows imports into installed dependencies | **can take hours, and may not finish at all** |

Measured on a 230-package langchain service:

| mode | result |
| --- | --- |
| `normal` | **64s**, all 21 project files translated, report produced |
| `full` | exceeded a **3 hour** job timeout having translated 6,100 dependency files and **1 of 21** project files, producing **no report** |

**Choose `full` only when the dependency tree is small enough to finish.** A
60-package Django service completes `full` in about 4 minutes and gains real
signal — SCA resolves `django` and `jwt`, so taint can be traced through
request handling, the ORM and auth. The same setting on a 230-package service
never terminates.

What `normal` gives up: third-party imports are logged as warnings rather than
resolved, so there is no dataflow *through* library internals. Findings whose
source and sink are both in your own code — hardcoded credentials, disabled TLS
verification, secrets in logs, SQL injection within a view — are unaffected.

Every run prints its coverage so a starved scan is visible rather than silent:

```
Translated 21 of 21 .py file(s) under services/chatbot/
```

If that reads `Translated 1 of 21`, the scan spent its budget inside
`site-packages` — switch to `normal`.

> `-exclude '**/site-packages/**'` and `-Dcom.fortify.sca.follow.imports=false`
> do **not** work for Python. Both were measured against the same service: the
> `-exclude` run translated *more* site-packages files than the baseline (5,695
> vs 5,687), and both still hit the cap. They are documented for
> JavaScript/TypeScript only. Use `translation-mode` instead.

#### Python package index

`pip-index-url` defaults to `https://pypi.org/simple/`. Point it at an internal
mirror if your runners are air-gapped, along with `uv-installer-base` and
`uv-python-install-mirror`. If the index is unreachable, `full` mode installs
nothing and the job says so:

```
WARNING: <path> declares dependencies but 0 packages installed into the venv.
```

## Notes:
For gradle projects, please ensure that you have configured a working gradle wrapper (gradlew) file in your repository. 

## Variants Available in Jfrog as of 05/06/2026

| Version            | Variants              |
|--------------------|-----------------------|
| `25.2.0`         | `jdk17-review` |
| `25.2.0`         | `jdk21-review` |

Note the image tag (`image-tag`, default `25.2.0`) versions the Fortify SCA
build and moves independently of this component's own version.


## Required CI/CD variable :zap: 

| CI/CD variable | Description | Remarks |
| --- | --- | --- |
| `ARTIFACTORY_USER` | If build requires pulling packages from artifactory | For Gradle Project
| `ARTIFACTORY_PASSWORD` | TOKEN for artifactory repository | For Gradle Project
| `SRM_API_KEY` | SRM API Key. Copy the whole key <br> `api-key:Redacted` | For SRM Upload
| `SRM_PROJECT_ID` | Refer to project id within SRM project link eg. `20` in `https://srm.com/srm/projects/20` | For SRM Upload


## Job Output

### Generated Artifacts

The following artifacts are generated and available for download:

- `fortify.html` - HTML report (Developer Workbook template)
- `fortify.pdf` - PDF report (Developer Workbook template)
- `fortify.xml` - XML report (Developer Workbook template)
- `scan.fpr` - Fortify Project Report file

### Build Behavior

- The scan will **fail** if critical or high severity issues are found
- Default had set `allow-failure: true` to prevent the job from blocking the pipeline
- Reports are generated even when the scan fails

## Support
For issues or questions, please contact the pipeline component maintainers.

## License
Internal pipeline component - All rights reserved.

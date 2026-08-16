<!-- Vendored snapshot: fetched 2026-08-16 from https://gitlab.com CI/CD Catalog (component tag 25.2.1, commit 16ea32d7) -->
# Fortify SAST Pipeline Component

A GitLab CI/CD pipeline component for integrating Fortify Static Application Security Testing (SAST) into your software development workflow. This component provides automated security scanning for multiple programming languages and integrates with both Gitlab vulnerability dashboard and Software Risk Measurement (SRM) for vulnerability tracking.

## Features

- **Multi-language Support**: Scan projects written in Python, JavaScript, Maven, or Gradle
- **Automated Security Scanning**: Integrates Fortify SCA for static code analysis
- **SRM Integration**: Optional upload of scan reports to Software Risk Measurement (SRM)
- **Gitlab vulnerability Dashboard Support**: Automatic upload of scan reportss to Gitlab Vulnerability dashboard
- **Configurable Job Settings**: Customize job names, stages, source paths, and failure behavior
- **Multiple Report Formats**: Generates HTML, PDF, and XML reports
- **Critical/High Issue Detection**: Fails builds when critical or high severity issues are found

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

```

## Notes:
For gradle projects, please ensure that you have configured a working gradle wrapper (gradlew) file in your repository. 

## Variants Available in Jfrog as of 05/06/2026

| Version            | Variants              |
|--------------------|-----------------------|
| `25.2.0`         | `jdk17-review` |
| `25.2.0`         | `jdk21-review` | 


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

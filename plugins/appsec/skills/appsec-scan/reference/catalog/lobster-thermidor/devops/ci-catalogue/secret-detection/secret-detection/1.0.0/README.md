<!-- Vendored snapshot: fetched 2026-08-16 from https://gitlab.com CI/CD Catalog (component tag 1.0.0, commit 64fee541) -->
# Secret Detection

This is a version of Gitlab Secret Detection v2.3.0  prepared for our platform

Gitlab Secret Detection is basically gitlab's native secret scanning tool

## Online documentation:

Read more about this feature here: https://docs.gitlab.com/ee/user/application_security/secret_detection.

Configure Secret Detection with CI/CD variables (https://docs.gitlab.com/ee/ci/variables/index.html).

List of available variables: https://docs.gitlab.com/ee/user/application_security/secret_detection/#available-cicd-variables

## Example

The following exmaple is a common way to use this component

```yaml
include:
  - component:  $CI_SERVER_FQDN/devops/ci-catalogue/secret-detection/secret-detection@main
    inputs:
      stage: security-scans
      tags: medium
# this job name is specified in the secret-detection component template code, secret-detection.yml
secret_detection:
  variables:
    SECRET_DETECTION_EXCLUDED_PATHS: "spec,docs,test"
    SECRET_DETECTION_HISTORIC_SCAN: "true"  # scans not just the incoming commit, but entire git history
```

## Inputs

| Input          | Default value                                  | Description                                                                                                                                                                                                                                                                                                                                     |
|----------------|------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `stage`        | `test`                                         | The stage where you want the job to be added.                                                                                                                                                                                                                                                                                                   || `image_tag`    | `7`                                            | Override the default version of the `secrets` analyzer image. The full image is `dock.artifactory.com/gitlab-scanners/secrets:7`                                                                                                                                                                                                                                                                                   |
| `enable_mr_pipelines` | `false`                                        | Set to `true` to enable `secret-detection` job to run on Merge Request Pipelines in addition to Branch Pipelines (except where there is an open MR on that Branch) |
| `tags` | ""     | custom tags  |


### Variables

You can customize secret detection by defining the following CI/CD variables:

| CI/CD variable | Description |
| -------------- | ----------- |
| `SECRET_DETECTION_EXCLUDED_PATHS` | Exclude vulnerabilities from output based on the paths. The paths are a comma-separated list of patterns. Patterns can be globs (see [doublestar.Match](https://pkg.go.dev/github.com/bmatcuk/doublestar/v4@v4.0.2#Match) for supported patterns), or file or folder paths (for example, `doc,spec`). Parent directories also match patterns. [Introduced](https://gitlab.com/gitlab-org/gitlab/-/issues/225273) in GitLab 13.3. |
| `SECRET_DETECTION_HISTORIC_SCAN` | Flag to enable a historic Gitleaks scan. |
| `SECRET_DETECTION_LOG_OPTIONS` | [`git log`](https://git-scm.com/docs/git-log) options used to define commit ranges. [Introduced](https://gitlab.com/gitlab-org/gitlab/-/issues/350660) in GitLab 15.1. |
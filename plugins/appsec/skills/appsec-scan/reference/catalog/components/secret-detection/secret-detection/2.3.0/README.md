# Secret Detection

Read more about this feature here: https://docs.gitlab.com/ee/user/application_security/secret_detection.

Configure Secret Detection with CI/CD variables (https://docs.gitlab.com/ee/ci/variables/index.html).

List of available variables: https://docs.gitlab.com/ee/user/application_security/secret_detection/#available-cicd-variables

## Usage

You should add this component to an existing `.gitlab-ci.yml` file by using the `include:`
keyword.

```yaml
include:
  - component: gitlab.com/components/secret-detection/secret-detection@<VERSION>
```

where `<VERSION>` is the latest released tag or `main`.

This component will add a `secret_detection` job to the pipeline.

If you are converting the configuration to use components and want to leverage the existing variable `$SECRET_DETECTION_DISABLED` you could conditionally include the component using the variable:

```yaml
include:
  - component: gitlab.com/components/secret-detection/secret-detection@main
    rules:
      - if: $SECRET_DETECTION_DISABLED == "true" || $SECRET_DETECTION_DISABLED == "1"
        when: never
```

Otherwise the job will run when applicable.

This assumes `SECRET_DETECTION_DISABLED` variable is already defined in `.gitlab-ci.yml` with either `'true'` or `'1'` as the value.

### Inputs

| Input          | Default value                                  | Description                                                                                                                                                                                                                                                                                                                                     |
|----------------|------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `stage`        | `test`                                         | The stage where you want the job to be added.                                                                                                                                                                                                                                                                                                   |
| `image_prefix` | `$CI_TEMPLATE_REGISTRY_HOST/security-products` | Override the name of the Docker registry providing the default images (proxy).                                                                                                                                                                                                                                                                  |
| `image_tag`    | `7`                                            | Override the default version of the `secrets` analyzer image.                                                                                                                                                                                                                                                                                   |
| `image_suffix` | `""`                                           | Suffix added to the image name. If set to -fips, [FIPS-enabled images](https://docs.gitlab.com/ee/user/application_security/secret_detection/#use-fips-enabled-images) are used for scan. [Introduced](https://gitlab.com/gitlab-org/gitlab/-/issues/355519) in GitLab 14.10.                                                                   |
| `enable_mr_pipelines` | `false`                                        | Set to `true` to enable `secret-detection` job to run on Merge Request Pipelines in addition to Branch Pipelines (except where there is an open MR on that Branch) |

### Variables

You can customize secret detection by defining the following CI/CD variables:

| CI/CD variable | Description |
| -------------- | ----------- |
| `SECRET_DETECTION_EXCLUDED_PATHS` | Exclude vulnerabilities from output based on the paths. The paths are a comma-separated list of patterns. Patterns can be globs (see [doublestar.Match](https://pkg.go.dev/github.com/bmatcuk/doublestar/v4@v4.0.2#Match) for supported patterns), or file or folder paths (for example, `doc,spec`). Parent directories also match patterns. [Introduced](https://gitlab.com/gitlab-org/gitlab/-/issues/225273) in GitLab 13.3. |
| `SECRET_DETECTION_HISTORIC_SCAN` | Flag to enable a historic Gitleaks scan. |
| `SECRET_DETECTION_LOG_OPTIONS` | [`git log`](https://git-scm.com/docs/git-log) options used to define commit ranges. [Introduced](https://gitlab.com/gitlab-org/gitlab/-/issues/350660) in GitLab 15.1. |

## Contribute

Please read about CI/CD components and best practices at: https://docs.gitlab.com/ee/ci/components 


This project provides components for the use of Static Application Security Testing as well as Infrastructure as Code scanning.

[[_TOC_]]

## Static Application Security Testing (SAST)

### Documentation References

Configuration for SAST can be performed through [CI/CD Variables](https://docs.gitlab.com/ee/ci/variables/index.html) or via the definition of [Inputs](https://docs.gitlab.com/ci/inputs/).

More information about GitLab SAST is available within [GitLab documentation](https://docs.gitlab.com/ee/user/application_security/sast/), along with the [available variables](https://docs.gitlab.com/ee/user/application_security/sast/index.html#available-cicd-variables).

### Usage

You should add this component to an existing `.gitlab-ci.yml` file by using the `include:`
keyword.

```yaml
include:
  - component: gitlab.com/components/sast/sast@<VERSION>
```

where `<VERSION>` is the latest released tag or `main`.

If you are converting the configuration to use components and want to leverage the existing variable `$SAST_DISABLED` you could conditionally include the component using the variable:

```yaml
include:
  - component: gitlab.com/components/sast/sast@main
    rules:
      - if: $SAST_DISABLED == "true" || $SAST_DISABLED == "1"
        when: never
      - when: always
```

Otherwise all SAST jobs will always run when applicable.

This assumes `SAST_DISABLED` variable is already defined in `.gitlab-ci.yml` with either `'true'` or `'1'` as the value.

### Inputs

| Input | Default value | Description |
| ----- | ------------- | ----------- |
| `enable_mr_pipelines` | `false` | Set it to `true` to enable jobs in [Merge Request Pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/) |
| `excluded_analyzers` | `""` | Comma separated list of analyzers that should not run |
| `excluded_paths` | `"spec, test, tests, tmp"` | Comma separated list of paths to exclude |
| `image_prefix` | `$CI_TEMPLATE_REGISTRY_HOST/security-products` | Define where all Docker image are pulled from |
| `image_suffix` | `""` | Suffix added to image. If set to `-fips`, [`FIPS-enabled` images](https://docs.gitlab.com/ee/user/application_security/sast/#fips-enabled-images) are used for scan. Only used by `semgrep` analyzer |
| `image_tag` | `"6"` | Tag of the Docker image to use |
| `run_advanced_sast` | `false` | Set it to `true` to enable [GitLab Advanced SAST](https://docs.gitlab.com/ee/user/application_security/sast/gitlab_advanced_sast.html) |
| `run_kubesec_sast` | `"false"` | Set it to `"true"` to run `kubesec-sast` job  |
| `search_max_depth` | `4` | Defines how many directory levels the search for programming languages should span |
| `stage` | `test`      | The stage where you want the job to be added |

## Infrastructure as Code (IaC) Scanning

### Documentation References

Configuration for IaC scanning can be performed through [CI/CD Variables](https://docs.gitlab.com/ee/ci/variables/index.html) or via the definition of [Inputs](https://docs.gitlab.com/ci/inputs/).

More information about GitLab Infrastructure as Code scanning is available within [GitLab documentation](https://docs.gitlab.com/user/application_security/iac_scanning/).

### Usage

You should add this component to an existing `.gitlab-ci.yml` file by using the `include:`
keyword.

```yaml
include:
  - component: gitlab.com/components/sast/iac-sast@<VERSION>
```

where `<VERSION>` is the latest released tag or `main`.

### Inputs

| Input | Default value | Description |
| ----- | ------------- | ----------- |
| `enable_mr_pipelines` | `false` | Set it to `true` to enable jobs in [Merge Request Pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/) |
| `excluded_paths` | `"spec, test, tests, tmp"` | Comma separated list of paths to exclude |
| `image_prefix` | `$CI_TEMPLATE_REGISTRY_HOST/security-products` | Define where all Docker image are pulled from |
| `image_suffix` | `""` | Suffix added to image. |
| `image_tag` | `"6"` | Tag of the Docker image to use |
| `search_max_depth` | `4` | Defines how many directory levels the search for programming languages should span |
| `stage` | `test`      | The stage where you want the job to be added |

## Contribute

Please read about CI/CD components and best practices at: https://docs.gitlab.com/ee/ci/components

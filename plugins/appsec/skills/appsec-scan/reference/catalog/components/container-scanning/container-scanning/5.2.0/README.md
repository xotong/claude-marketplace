# Container Scanning

## Usage

Use this component to enable container scanning in your project.
You should add this component to an existing `.gitlab-ci.yml` file by using the `include:`
keyword.

```yaml
include:
  - component: gitlab.com/components/container-scanning/container-scanning@<VERSION>
```

where `<VERSION>` is the latest released tag or `main`.

This will add a `container_scanning` job to the pipeline.

The template should work without modifications but you can customize the template settings if
needed: https://docs.gitlab.com/ee/user/application_security/container_scanning/#customizing-the-container-scanning-settings

For details, see the following links:
- https://docs.gitlab.com/ee/user/application_security/container_scanning/index.html#overriding-the-container-scanning-template
- https://docs.gitlab.com/ee/user/application_security/container_scanning/#vulnerability-allowlisting
- List of available variables: https://docs.gitlab.com/ee/user/application_security/container_scanning/#available-variables
- For auto-remediation, a readable Dockerfile in the root of the project or as defined by the
  CS_DOCKERFILE_PATH variable.

## Contribute

Please read about CI/CD components and best practices at: https://docs.gitlab.com/ee/ci/components

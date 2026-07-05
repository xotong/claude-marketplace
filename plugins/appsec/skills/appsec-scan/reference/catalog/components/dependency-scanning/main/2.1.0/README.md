<!-- Vendored snapshot: fetched 2026-07-04 from gitlab.com CI/CD Catalog (component tag 2.1.0) -->
# Component for Dependency and License Scanning

This component generates a CycloneDX Software Bill of Materials, which is
used by GitLab to identify a project's dependencies, and their licenses. This
[CycloneDX Software Bill of Materials] is compatible with the [GitLab taxonomy].
Additionally, this component is capable of generating a [Dependency Scanning report]
from the vulnerabilities detected in the project's dependencies.

## Requirements

This CI/CD component requires GitLab [dependency scanning] capabilities, a
[GitLab Ultimate][Ultimate] feature.

## Usage

Add the following snippet to your `.gitlab-ci.yml` to run the `dependency-scanning`
job with the default configuration.

```yaml
include:
  - component: $CI_SERVER_FQDN/components/dependency-scanning/main@<VERSION>
```

You can also customize the job uisng the CI/CD component's inputs. For example,
you can configure the log level and the job stage with the following configuration.

```yaml
include:
  - component: $CI_SERVER_FQDN/components/dependency-scanning/main@<VERSION>
    inputs:
      log_level: "debug"
      stage: "security-scanning"
```

> [!note]
> Make sure to set the component's version. Released versions may be found in the
> [tags section](https://gitlab.com/components/dependency-scanning/-/tags) of the
> project. More information on component versioning and available options may be
> found in [component versions documentation](https://docs.gitlab.com/ee/ci/components/#component-versions).

### Inputs

Please see the [catalog page](https://gitlab.com/explore/catalog/components/dependency-scanning)
for the complete list of allowed inputs.

## Contribute

1. Read how to [contribute to GitLab development](https://docs.gitlab.com/ee/development/contributing/)
   and the [Development guide for GitLab official CI/CD components](https://docs.gitlab.com/ee/development/cicd/components.html).
2. Submit a merge request, and follow the bot instructions.

## Release process

1. Promote unreleased changelogs with `changie batch auto`.
1. Update `CHANGELOG.md` with `changie merge`.
1. Create a new release using the latest version in the changelog with `git tag "$(changie latest -r)" && git push origin "$(changie latest -r)"`.

[CycloneDX Software Bill of Materials]: https://docs.gitlab.com/ee/ci/yaml/artifacts_reports.html#artifactsreportscyclonedx 
[Dependency Scanning Report]: https://docs.gitlab.com/ci/yaml/artifacts_reports/#artifactsreportsdependency_scanning
[GitLab taxonomy]: https://docs.gitlab.com/ee/development/sec/cyclonedx_property_taxonomy.html
[Dependency Scanning]: https://docs.gitlab.com/ee/user/application_security/dependency_scanning/
[Ultimate]: https://about.gitlab.com/pricing/feature-comparison/

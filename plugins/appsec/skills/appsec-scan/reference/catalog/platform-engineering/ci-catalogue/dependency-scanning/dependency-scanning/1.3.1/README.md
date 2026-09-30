<!-- Vendored snapshot: fetched 2026-09-30 from https://gitlab.example.com CI/CD Catalog (component tag 1.3.1, commit 3b53874f) -->


The following exmaple is a common way to use this component

```yaml
include: 
  - component: $CI_SERVER_FQDN/platform-engineering/ci-catalogue/dependency-scanning/dependency-scanning@~latest
    inputs:
      stage: scans
      language: javascript
      resolution_job_variant: openjdk17 # or openjdk21
```

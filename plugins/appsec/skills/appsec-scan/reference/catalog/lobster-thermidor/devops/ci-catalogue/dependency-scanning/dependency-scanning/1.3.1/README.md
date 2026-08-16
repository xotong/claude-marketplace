<!-- Vendored snapshot: fetched 2026-08-16 from https://gitlab.com CI/CD Catalog (component tag 1.3.1, commit b2103483) -->


The following exmaple is a common way to use this component

```yaml
include: 
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/container-scanning/ container-scanning@~latest
    inputs:
      stage: scans
      language: javascript
      variant: openjdk17 # or openjdk21
```

<!-- Vendored snapshot: fetched 2026-09-23 from https://gitlab.example.com CI/CD Catalog (component tag 1.2.0, commit a50b3a0d) -->


The following exmaple is a common way to use this component

```yaml
include: 
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/container-scanning/ container-scanning@~latest
    inputs:
      stage: scans
      language: javascript
      variant: openjdk17 # or openjdk21
```

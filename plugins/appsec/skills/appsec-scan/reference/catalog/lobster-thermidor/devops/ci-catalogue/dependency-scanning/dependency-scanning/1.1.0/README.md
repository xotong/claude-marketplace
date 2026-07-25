<!-- Vendored snapshot: fetched 2026-07-25 from gitlab.com CI/CD Catalog (component tag 1.1.0) -->


The following exmaple is a common way to use this component

```yaml
include: 
  - component: $CI_SERVER_FQDN/lobster-thermidor/devops/ci-catalogue/container-scanning/ container-scanning@~latest
    inputs:
      stage: scans
      language: javascript
      variant: openjdk17 # or openjdk21
```

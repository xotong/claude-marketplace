# Scanner preferences — admin guide

`scanner-preferences.yaml` is the single admin-owned control point for which
scanner runs for each security category. It is versioned in this repo, so
changes go through an MR with Platform Team approval (CODEOWNERS). Users never
pick scanners — the skill reads this file on every run.

## Switching profiles

```bash
export APPSEC_PROFILE=public-test   # one env var — that's the whole switch
```

Unset, the `default_profile` at the top of the YAML applies. Shipped profiles:

| Profile | Purpose |
|---|---|
| `company` | Production preferences: Fortify for SAST (licensed internal images), GitLab analyzers for dependency / secret / container scanning, DAST as CI-only reference. |
| `public-test` | Full end-to-end test against the public gitlab.com catalog and public analyzer images. No internal infrastructure needed. |

## Schema

```yaml
default_profile: <name>            # used when APPSEC_PROFILE is unset
profiles:
  <name>:
    gitlab_instance: <https url>   # the ONLY host the skill talks to at runtime
    catalog_auth: none | <ENV_VAR_NAME>   # env var holding a read_api PAT
    categories:
      <category>:                  # sast | dependency_scanning | secret_detection
                                   # | container_scanning | dast_web | dast_api
        components: [<project-path>/<component-name>, ...]   # catalog paths
        runners: [<scanners/*.sh filename> | none, ...]      # local executors
        enabled: true|false
    additional_scanners:           # legacy env-var-driven scanners (v1 behavior)
      <key>: { runner: <file>, image_env: <VAR>, condition: <flag> }
```

- **components** are CI/CD Catalog paths on `gitlab_instance`. On every run the
  skill resolves each one via `scripts/catalog.sh`: lists `/repository/tags`,
  picks the highest stable semver (prereleases and `-suffixed` tags excluded),
  fetches that version's template (`spec:inputs`) and README, caches them under
  `.appsec-results/catalog/`, and prints drift warnings against the local
  runner. Offline, it falls back to the snapshots in `../reference/catalog/`.
- **runners** are the local execution shims in `scanners/` that run *inside*
  the analyzer image the catalog resolved. `none` = category is CI-only; the
  skill emits a ready-to-paste `include: component:` snippet instead.
- **catalog_auth**: `none` works for public projects. For an internal instance
  that requires auth, set it to the *name* of an env var (e.g.
  `GITLAB_COMPANY_TOKEN`) holding a `read_api` PAT; the skill fails preflight
  if that variable is empty.

## Changing a preference (admin)

Point the category at a different component and/or runner — one line each:

```yaml
sast:
  components: [devops/ci-catalogue/fortify-scan-python3]   # ← swap component
  runners: [fortify-python.sh]                             # ← swap executor
```

Add a new profile by copying `public-test` and adjusting `gitlab_instance`,
`catalog_auth`, and paths. Remove an `additional_scanners` entry to retire a
legacy scanner.

## Category notes

- **sast (company = Fortify)**: Fortify has no free local mode; the runners use
  the licensed images from the internal registry (env `APPSEC_REGISTRY` +
  `FORTIFY_PY_IMAGE`/`FORTIFY_JS_IMAGE`, unchanged from v1). `public-test` uses
  the GitLab Semgrep analyzer.
- **dependency_scanning**: the GitLab analyzer generates an **SBOM** locally
  (`gl-sbom-*.cdx.json`); vulnerability matching happens inside GitLab after
  push. The local run mirrors the licensed CI environment via
  `GITLAB_FEATURES=dependency_scanning` (your org holds the Ultimate license
  that enables this in CI). A lock file (package-lock.json, poetry.lock,
  pip-compile requirements, …) is required — plain manifests are skipped.
- **secret_detection**: full local findings + remediation loop (see SKILL.md).
- **container_scanning (GTCS)**: scans the image named by `CS_IMAGE` (or
  `CI_APPLICATION_REPOSITORY` + `CI_APPLICATION_TAG`).
- **dast_web / dast_api**: CI-only by design — DAST needs a running deployed
  target, which does not exist pre-push. The skill gathers the inputs a CI DAST
  job needs (target URL, OpenAPI spec, Postman collection — auto-detected from
  the repo or requested from you) and emits the include snippet. For local
  design-time DAST coverage, use the `appsec-dast-sim` skill.

## Per-run env overrides (users)

Image location overrides keep working as in v1 (e.g. `SECRET_DETECTION_IMAGE`,
`GITLAB_SAST_IMAGE`, `APPSEC_REGISTRY`, …) — see the Prerequisites table in
SKILL.md. They override *where images come from*, never *which scanner runs*;
that is this file's job.

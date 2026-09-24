# appsec-sbom-matcher (remote GitLab-native dependency scanning)

## What this is

`scripts/remote-match.sh` gets **GitLab-native** dependency-scanning results
(the server-side SBOM-to-advisory matching that only runs inside a real
GitLab CI pipeline with a real `CI_JOB_TOKEN`) for a repo scanned **locally**,
by shipping only that repo's dependency manifests/lockfiles to a small helper
project on a self-hosted GitLab instance, triggering a real pipeline there,
and pulling back `gl-dependency-scanning-report.json`.

The helper project itself is a fixed, already-deployed GitLab project —
`.gitlab-ci.yml` in this directory is a **verbatim** copy of the one at
`platform-engineering/skillshub/appsec-sbom-matcher` (project id 44) on
`gitlab.example.com`, kept here for reference and disaster recovery. Do
not edit it and expect it to take effect anywhere — the live project is the
source of truth; re-fetch and diff before assuming this copy is current:

```
glab api --hostname <host> projects/<id>/repository/files/.gitlab-ci.yml/raw?ref=main
```

## How it works

1. `spec:inputs` declares `language` (maven|gradle|python|javascript|go),
   `bundle` (a generic-package version id) and `ds_version` (component
   version to include, default `1.2.0`).
2. It includes the private `dependency-scanning` CI/CD Catalog component with
   `inputs.language` forwarded, so the component's own job runs with a real
   `CI_JOB_TOKEN` — that's what lets GitLab's server-side SBOM matching
   produce a report instead of the offline/local fallback.
3. A `.pre` stage job, `fetch-bundle`, downloads `bundle.tar.gz` from this
   project's generic package registry (`appsec-bundles/<bundle id>`) using
   `JOB-TOKEN: $CI_JOB_TOKEN` and extracts it into the job workspace, so the
   component's `dependency-scanning` job (stage `test`, `allow_failure: true`)
   sees the manifests as if they were checked into the repo.

Findings never enter this project's own Vulnerability Report because the
pipeline runs on the **non-default** branch `scan`, not `main`.

## Setting this up on another GitLab instance

1. Create a **private** project (Developer role is enough to use it day to
   day; only project owners need to set it up).
2. Default branch `main`; also create a `scan` branch (can be empty besides
   the CI file — findings are only kept off the Vulnerability Report by
   scanning a non-default branch, so `scan` must stay non-default forever).
3. Copy this directory's `.gitlab-ci.yml` to the project root on `main` and
   `scan` (or just `scan`, since the pipeline is always triggered against
   `scan` — but keep `main` in sync so a diff always shows drift, not a
   deliberate feature).
4. Enable the project's generic package registry (on by default; check
   Settings > General > Visibility if it was disabled instance-wide).
5. Ensure a runner is available to the project that can pull
   `curlimages/curl:8.11.0` and whatever image the pinned
   `dependency-scanning` component version resolves to (see the maven/gradle/
   python limitation below).
6. Point `remote-match.sh --instance <url> --matcher-project <id-or-path>` at
   it, with a token in `APPSEC_RESOLVED_TOKEN`.

## Access model

- **Developer**: enough to upload a bundle (generic package registry write),
  trigger the pipeline (`POST .../pipeline`), and read pipeline/job status,
  traces, and artifacts. This is what day-to-day laptop use needs.
- **Maintainer**: required to `DELETE` a generic package version. Most
  callers won't have this — `remote-match.sh` treats a `403` on cleanup as
  non-fatal (`ADVISORY: could not delete bundle <id> ...`) and leaves the
  bundle for the platform team's own scheduled cleanup (a package-registry
  cleanup policy on `appsec-bundles`, or a periodic job, should exist so
  Developer-only callers don't accumulate bundles indefinitely).

## What leaves the laptop

Only the dependency manifests/lockfiles for the language being scanned
(e.g. `package.json` + `package-lock.json`, or `pom.xml` + `.mvn/`) —
never application source code. Each upload is a single `bundle.tar.gz`
generic package version named `<language>-<UTC timestamp>-<random hex>`;
`remote-match.sh` deletes it after collecting the report (see the access
model above for what happens when it can't).

## Known limitation: maven (resolution-job toolbox image)

A maven bundle with no committed `.mvn/`-pinned versions needs the
`dependency-scanning` component's resolution job, which pulls a toolbox
image. If that image isn't mirrored on a given estate's runners, the
resolution job fails with an image-pull error (`fetch-bundle` still
succeeds; it's the language-specific resolution job that fails).
`remote-match.sh` reports this as a per-language `failed` status with the
pull-denied line from the job trace as the reason.

Verified against `gitlab.example.com` project 44 (crAPI, 2026-09-23,
auto-detected bundles): `javascript` (146 findings), `python` (84),
`gradle` (19), and `go` (26) all completed with `status: ok` — none of them
needed a resolution job (their lockfiles/wrapper metadata already pin exact
versions). `maven` was not exercised in that run (crAPI has no `pom.xml`);
treat the toolbox-image limitation above as maven-specific and unconfirmed
either way until a maven bundle is actually run against a given instance.

## Access and hardening (as deployed on gitlab.example.com)

- **Access by group, not by person:** Manage → Members → *Invite a group* with the
  Developer role, once per team. New team members get access automatically.
- **Branches are locked:** a protected-branch rule `*` with push = No one and
  merge = Developers + Maintainers. Developers can run scan pipelines on `scan` but
  nobody can push or create branches, so the pipeline definition cannot be changed
  through a developer's access. To edit the CI, a Maintainer lifts the `*` rule,
  commits to `main` and `scan`, and restores it.
- **No pipeline variables:** *Settings → CI/CD → Variables → Minimum role to use pipeline
  variables* = No one allowed (`ci_pipeline_variables_minimum_override_role`). Variables
  override job variables such as the analyzer image, so allowing them would let anyone who
  can start a scan run their own image on the runner. The skill passes only pipeline
  inputs, which this does not affect.
- **Short retention:** bundles are deleted after each scan, and the `dependency-scanning`
  report plus the resolution jobs' artifacts expire after 1 hour, so teams cannot browse
  each other's dependency findings later.


# Scanner preferences — admin guide

`scanner-preferences.yaml` is the single admin-owned control point for this
skill. It is versioned, so changes go through an MR with Platform Team approval
(CODEOWNERS). Users never pick scanners — the skill reads this file each run.

Design principle for self-hosted / airgap environments: **everything is
declared here so the model only reads config, never guesses endpoints.** Pin
`image:` values explicitly; do not rely on the model to infer registry paths.

## Switching profiles

```bash
export APPSEC_PROFILE=public-test   # one env var — the whole switch
```

Unset → the `default_profile` at the top of the file applies.

| Profile | Purpose |
|---|---|
| `company` | Production preferences: internal GitLab + internal JFrog images. Edit the placeholder `gitlab_instance`, `component:` and `image:` values to your paths. |
| `public-test` | End-to-end test against the public gitlab.com catalog + public analyzer images. Needs internet; **refused when `settings.airgap: true`**. |

## Global `settings:` block

```yaml
settings:
  airgap: true|false          # true = no public internet; internal endpoints only
  container_runtime: auto     # auto (docker then podman) | docker | podman
  jq:
    prefer: host              # use PATH jq if present
    install_url: ""           # optional: fetch jq if missing ({os}/{arch} filled from uname)
  catalog:
    mode: online              # online = resolve live | offline = snapshots only
    auth_token_env: ""        # env var NAME holding a read_api PAT (blank = anonymous)
  container_registry:
    user_env: CS_REGISTRY_USER      # env var NAMES holding registry creds
    password_env: CS_REGISTRY_PASSWORD
```

- **airgap** — `true` keeps the skill on the active profile's `gitlab_instance`
  and the configured image registry only, refuses the `public-test` profile, and
  does not treat "no internet" as an error. Set `false` when you have internet.
- **container_runtime** — the skill detects docker, then podman. Force one if
  both are present. The container-scan verbs used (`build`, `save`, `run`,
  `pull`) are identical across docker and podman.
- **jq** — powers the Step 5 severity summary and is **optional**. If jq is not
  on `PATH` and `install_url` is set, the skill downloads it (once, to
  `.appsec-results/bin/`); `{os}` and `{arch}` are filled from `uname` (e.g.
  `linux/amd64`, `darwin/arm64`) so one URL can serve mixed fleets. Leave
  `install_url` empty to simply show `UNKNOWN` counts when jq is absent — the
  scan still runs.
- **catalog.mode** — `online` resolves component versions live against
  `gitlab_instance` each run; `offline` skips the network and uses the vendored
  snapshots in `../reference/catalog/`.
- **catalog.auth_token_env** — the skill tries **anonymous** API reads first. If
  your instance rejects them, create a `read_api` PAT, put it in an env var, and
  name that var here (e.g. `GITLAB_READ_TOKEN`). Preflight then requires it.
- **container_registry** — env var *names* (not values) holding the registry
  credentials used both when GTCS pulls a BYO image and when a local build must
  pull a `FROM` base from the internal registry.

## Per-category settings

```yaml
categories:
  sast:
    component: components/sast/sast              # CI/CD Catalog path (resolve + README)
    image: jfrog.internal/security/semgrep:6     # what actually RUNS — admin-pinned
    runner: gitlab-sast.sh                        # local executor, or "none"
    enabled: true
```

The six categories are `sast`, `dependency_scanning`, `secret_detection`,
`container_scanning`, `dast_web`, `dast_api`.

- **`image:` is what runs** — edit this to your JFrog path. It is deliberately
  decoupled from the catalog so a version bump can never surprise you: the
  pinned image is what executes.
- **`component:` is resolved every run** for two things: the component's own
  usage guide (its README, cached under `.appsec-results/catalog/` — ask the
  skill to summarize it), and a **drift advisory** that tells you when the
  component's declared image tag has moved ahead of your pinned `image:`, i.e.
  when to bump it. Customised components in your catalog resolve the same way —
  just point `component:` at your fork's path.
- **`runner: none`** = category is CI-only; the skill emits an
  `include: component:` snippet instead of running locally (DAST).

## Category notes

- **sast** — `company` pins the Fortify or GitLab SAST image you mirror; the
  Semgrep analyzer's rules are baked into the image (no network inside).
- **dependency_scanning** — generates an **SBOM** locally
  (`gl-sbom-*.cdx.json`); vulnerability matching happens in GitLab after push.
  The skill passes `GITLAB_FEATURES=dependency_scanning` to mirror the licensed
  CI environment. A lock file is required; plain manifests are skipped.
- **secret_detection** — full local findings + the remediation loop.
- **container_scanning** — see the dedicated section below.
- **dast_web / dast_api** — CI-only by design (DAST needs a running deployed
  target). The skill gathers inputs (target URL, OpenAPI, Postman) and emits the
  include snippet. For local design-time coverage use the `appsec-dast-sim` skill.

## Container scanning: how the target image is chosen

GTCS (`gtcs scan`) is **registry-only** — it cannot scan a locally-built image.
So the skill uses two paths automatically:

1. **BYO registry image** — set `CS_IMAGE=<image:tag>` (already built and pushed
   to your registry). GTCS pulls and scans it, using
   `settings.container_registry` creds for private registries. This is
   CI-identical.
2. **Local Dockerfile** — if `CS_IMAGE` is unset and a `Dockerfile` is present,
   the skill builds it (`<runtime> build`), saves it to a tarball
   (`<runtime> save`), and scans the tarball with the analyzer image's **bundled
   Trivy** (`--input … --offline-scan`) — no registry, no root, no socket, fully
   offline. Set `DOCKERFILE=<path>` to choose among multiple Dockerfiles.
3. Neither → container scanning is deferred to CI (an include snippet is shown).

If a local build fails because a `FROM` base image cannot be pulled from your
internal registry, the skill tells you to run `<runtime> login <registry-host>`
(or set the `container_registry` credential env vars) and points the Dockerfile
`FROM` at the internal mirror. Any other build error prints
"Submit a Jira ticket under others".

## Legacy `additional_scanners`

Parasoft, Pylint, ESLint, Scantist, and Trivy keep their v1 env-var behavior
(image from `APPSEC_REGISTRY` + the named `image_env`). Remove an entry to
retire that scanner.

## Per-run env overrides (users)

`CS_IMAGE`, `DOCKERFILE`, and the image/registry env vars override for a single
run. They change *where images come from* or *what is scanned*, never *which
scanner runs* — that is this file's job.

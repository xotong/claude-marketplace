# Scanner preferences — admin guide

`scanner-preferences.yaml` is the single admin-owned control point for this
skill. It is versioned, so changes go through an MR with Platform Team approval
(CODEOWNERS). Users never pick scanners — the skill reads this file each run.

Design principle for self-hosted / airgap environments: **everything is
declared here so the model only reads config, never guesses endpoints.** Pin
`image:` values explicitly; do not rely on the model to infer registry paths.
`scripts/load-prefs.sh` converts this file into shell variables and `RUN_*`
flags — the model never parses the YAML itself.

## Switching profiles

```bash
export APPSEC_PROFILE=catalog   # one env var — the whole switch
```

Unset → the `default_profile` at the top of the file applies.

| Profile | Purpose |
|---|---|
| `catalog` | Default: resolves components live from gitlab.com (lobster-thermidor/devops/ci-catalogue). Needs internet. **Refused when `settings.airgap: true`** (gitlab.com = public internet). |
| `company` | Production preferences: internal GitLab mirror + internal JFrog images. Edit the placeholder `gitlab_instance`, `component:` and `image:` values to your paths. Airgap-safe. |

## Global `settings:` block

```yaml
settings:
  airgap: false               # shipped default; set true for internal-only environments
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

- **airgap** — `false` is the shipped default (catalog profile points at
  gitlab.com and needs internet). Set `true` for environments with no public
  internet access. When `airgap: true`, any profile whose `gitlab_instance`
  contains `gitlab.com` is refused at load time — use the `company` profile
  (pointing at your internal mirror) instead. The scan keeps working fully
  offline via the vendored snapshots in `reference/catalog/`.
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
    component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
    version: ~latest          # ~latest OR an exact tag e.g. "25.2.0"
    image: registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sca:25.2.0-jdk17-review
    runner: fortify-sast.sh
    enabled: true
```

The four categories are `sast`, `dependency_scanning`, `secret_detection`,
`container_scanning`.

- **`image:` is what runs** — edit this to your JFrog mirror path. It is
  deliberately decoupled from the catalog so a version bump can never surprise
  you: the pinned image is what executes.
- **`version:` controls catalog resolution** — two modes:
  - `~latest` (default) — `catalog.sh` resolves the highest stable release tag
    each run and uses it. Keeps you current without manual bumps.
  - Exact tag (e.g. `"25.2.0"`) — pins the component version used for drift
    comparison and AGENTS.md lookup. If a newer stable tag exists, `catalog.sh`
    prints: `ADVISORY: <component> pinned <X>, newer stable <Y> available` —
    surface this to the admin. When you're ready to upgrade, bump `version:` and
    update `image:` to match.
- **`component:` is resolved every run** for three things: the component's usage
  guide (README, cached under `.appsec-results/catalog/`), the agent-oriented
  reference (AGENTS.md, also cached), and a **drift advisory** that tells you
  when the component's declared image tag has moved ahead of your pinned `image:`.
- **`runner: none`** = category is CI-only; no local run.

## How to pin an exact component version (Platform Team how-to)

1. Decide the tag to pin (e.g. `25.2.0` for fortify-sast).
2. In the relevant category block, set `version: "25.2.0"`.
3. Optionally update `image:` to the matching image tag to keep drift
   advisory clean.
4. Refresh the vendored snapshot so offline fallback stays current:
   see UPDATE-GUIDE.md Scenario 6.
5. Open an MR. The ADVISORY line on future runs reminds you when a newer
   stable tag is available.

## Category notes

- **sast** — Fortify SCA multi-language scanner. Language auto-detected from
  project files (gradle > maven > python > javascript); set `FORTIFY_LANGUAGE`
  to override. The FPR output (`.appsec-results/fortify-sast.fpr`) contains the
  full severity breakdown; the local summary shows total vulnerability count.
- **dependency_scanning** — generates an **SBOM** locally
  (`gl-sbom-*.cdx.json`); vulnerability matching happens in GitLab after push.
  The skill passes `GITLAB_FEATURES=dependency_scanning` to mirror the licensed
  CI environment. A lock file is required; plain manifests are skipped.
- **secret_detection** — full local findings + the remediation loop.
- **container_scanning** — see the dedicated section below.

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

## Per-run env overrides (users)

`CS_IMAGE`, `DOCKERFILE`, `FORTIFY_LANGUAGE`, and the image env vars override
for a single run. They change *where images come from*, *what is scanned*, or
*which Fortify language is used* — never *which scanner runs* (that is this
file's job).

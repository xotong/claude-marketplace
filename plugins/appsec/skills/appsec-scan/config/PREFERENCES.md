# Scanner preferences — admin guide

> **Who this is for:** Platform Team admins who own `scanner-preferences.yaml`.
> Developers running scans want [`../README.md`](../README.md) instead.
>
> **Common tasks:** [switch profile](#switching-profiles) · [pin a component version](#how-to-pin-an-exact-component-version-platform-team-how-to) · [container scan target](#container-scanning-how-the-target-image-is-chosen)

`scanner-preferences.yaml` is the single admin-owned control point for this
skill. It is versioned, so changes go through an MR with Platform Team approval
(CODEOWNERS). Users never pick scanners — the skill reads this file each run.

Design principle for self-hosted / airgap environments: **everything is
declared here so the model only reads config, never guesses endpoints.** Pin
`image:` values explicitly; do not rely on the model to infer registry paths.
`scripts/load-prefs.sh` converts this file into shell variables and `RUN_*`
flags — the model never parses the YAML itself.

**Platform support:** macOS, Linux, and WSL2 are fully supported. Native Windows
requires Git for Windows (Git Bash) so Claude Code can run `.sh` scripts, plus
Docker Desktop; WSL2 is strongly recommended instead. See [`../README.md`](../README.md)
for the full matrix. Auto-download of `python3`/`jq` does not work in native Git Bash —
install them in the environment (on WSL2/Linux the `install_url` path works).

## Switching profiles

```bash
export APPSEC_PROFILE=catalog   # one env var — the whole switch
```

Unset → the `default_profile` at the top of the file applies.

| Profile | Purpose |
|---|---|
| `catalog` | Default: resolves components live from gitlab.com (lobster-thermidor/devops/ci-catalogue). Needs internet **and a `read_api` PAT in `$GITLAB_READ_TOKEN`** — that catalogue is private, so anonymous reads 404. Setup: MIGRATION.md step 0. **Refused when `settings.airgap: true`** (gitlab.com = public internet). |
| `company` | Production preferences: internal GitLab mirror + internal JFrog images. Edit the placeholder `gitlab_instance`, `component:` and `image:` values to your paths. Airgap-safe. |

## Global `settings:` block

```yaml
settings:
  airgap: false               # shipped default; set true for internal-only environments
  container_runtime: auto     # auto (docker then podman) | docker | podman
  jq:
    prefer: host              # use PATH jq if present
    install_url: ""           # optional: fetch jq if missing ({os}/{arch} filled from uname)
  python:
    prefer: host              # use PATH python3 if present
    install_url: ""           # optional: fetch portable python3 tarball if missing
  ci_gate:
    fail_on: high             # critical | high | medium | none
  image_policy: follow-component   # follow-component | pinned
  catalog:
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
- **jq** — powers legacy count parsing and is **optional**. If jq is not on
  `PATH` and `install_url` is set, the skill downloads it (once, to
  `.appsec-results/bin/`); `{os}` and `{arch}` are filled from `uname` (e.g.
  `linux/amd64`, `darwin/arm64`) so one URL can serve mixed fleets. Leave
  `install_url` empty to degrade to UNKNOWN severity counts — the scan still runs.
- **python** — powers `scripts/normalize.py` (findings.triaged.json, gate). Three tiers:
  1. **Host python3** (preferred) — `scripts/resolve-python.sh` uses `python3` from PATH.
  2. **install_url download** — if host python3 is absent and `install_url` is set, the
     skill downloads a portable python3 tarball and extracts it to `.appsec-results/bin/`.
     Template uses `{os}` and `{arch}` (e.g. `linux/amd64`); admin hosts tarballs on the
     platform artifact server (see MIGRATION.md step 2).
  3. **Legacy degrade** — if neither is available, falls back to jq-based counts with
     UNKNOWN `verification_status` on all findings.
- **ci_gate** — `settings.ci_gate.fail_on` controls the severity threshold at which
  `scripts/run-scan.sh` exits 1 (gate failed). Values: `critical` | `high` (default) |
  `medium` | `none`. Set `none` to always exit 0 (report-only mode). `likely_false_positive`
  findings still count toward the gate — dismiss them in GitLab's Vulnerability Report.
- **image_policy** — which scanner image tag actually runs.
  - `follow-component` (default) — track the component automatically. The category's
    `image:` supplies the **registry and path** (your mirror); the component template
    at the resolved tag supplies the **tag**. A component moving to `8.6.31` gives you
    `<your-registry>/container-scanning:8.6.31` with no config edit and no pull from a
    public registry. The candidate is pulled first as an availability check — if your
    mirror does not carry that tag yet, the run prints exactly what to mirror and falls
    back to `image:` rather than failing. Skipped under `--dry-run` (no network).
  - `pinned` — always use `image:` verbatim. No adoption, no pull check. Use when you
    need byte-identical reproducibility.

  Note `image:` is still required under `follow-component`: it is what the effective
  ref is built from, and the fallback when adoption is not possible.
- **package_registries** — URL templates used to check, before the fix loop runs,
  whether a suggested upgrade is obtainable here. All empty (the shipped default)
  disables the check entirely. Placeholders: `{package}` `{version}` `{group_path}`
  `{artifact}` `{module}`.

  Verdicts and what they do:

  | Verdict | Meaning | Effect |
  |---|---|---|
  | available | 200, version confirmed | stays `fixable_candidate` — loop may attempt it |
  | absent | 404 | `blocked_registry_gap` — loop skips it, TRIAGE.md §3b lists it |
  | unknown | timeout, auth failure, 5xx, no template | nothing changes |

  `unknown` deliberately changes nothing: a registry you could not reach is not
  evidence a package is missing, and treating it as one would send developers
  chasing mirroring requests for packages that are already there.

  Gap findings still count toward the gate — a vulnerability you cannot fix yet is
  still a vulnerability. Container-scanning findings are never probed: those are OS
  packages in a base image, fixed by rebuilding on a newer base.
- **catalog resolution** — there is no mode switch. Components are always
  resolved live against the active profile's `gitlab_instance`; if that fetch
  fails for any reason, `catalog.sh` falls back to the vendored snapshots in
  `../reference/catalog/` and says `[offline-fallback]`.

  A forced-offline setting was removed on 2026-07-25 because it provided nothing
  the rest of the design did not already give — exact `version:` pins provide
  reproducibility, and the automatic fallback provides airgap resilience — while
  costing real safety: it silently disabled image and contract drift detection,
  since `scanners/*.contract` are generated from the very snapshots the check
  would compare against, so the comparison could never fail. It also risked
  serving snapshots vendored from a *different* instance as though they were
  yours. `scripts/catalog.sh resolve --offline` still exists for tests and
  one-off manual use.

- **catalog.auth_token_env** — the env var *name* holding a `read_api` PAT for
  the **GitLab API only**. It authenticates catalog metadata reads (tags,
  `template.yml`, `README.md`, `AGENTS.md`) and nothing else — it is **not**
  used to pull scanner images. Image credentials are `container_registry`
  below, a separate setting.

  Whether you need it depends solely on whether your instance serves those
  projects to unauthenticated API reads. Being on the internal network does not
  authenticate you to GitLab. Test it:

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' \
    https://<your-gitlab>/api/v4/projects/<group>%2F<project>/repository/tags
  ```

  `200` → set `auth_token_env: ""`. `401`/`404` → keep a PAT.
  Ships as `GITLAB_READ_TOKEN` because the `lobster-thermidor` catalogue is
  private on gitlab.com: anonymous reads return `404`. Whenever this names a
  var, preflight requires that var to be non-empty — deliberately, so a
  tokenless run cannot quietly fall back to vendored snapshots and look like a
  live catalog test. Set it to `""` when the instance serves the components
  anonymously — that is how the `company` profile ships. Token setup:
  MIGRATION.md step 0.

  **Per profile.** `auth_token_env` may be set inside a profile block, next to
  `gitlab_instance`, because it is a property of that instance. A profile value
  (including an explicit `""`) overrides `settings.catalog.auth_token_env`,
  which remains the default for profiles that do not set one. This is what lets
  the gitlab.com `catalog` profile require a PAT while the internal `company`
  profile reads anonymously.
- **container_registry** — env var *names* (not values) holding the **image
  registry** credentials, used when GTCS pulls a BYO image and when a local
  build must pull a `FROM` base. If your registry (e.g. a JFrog mirror) allows
  anonymous pull, simply leave those env vars unset — the names can stay as
  they are and empty values are passed through harmlessly. Unrelated to
  `catalog.auth_token_env`.

## Per-category settings

```yaml
categories:
  sast:
    component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
    version: ~latest          # ~latest OR an exact tag e.g. "25.2.0"
    image: registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/fortify-sca:25.2.0-jdk17-review
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

# Scanner preferences — admin guide

> **Who this is for:** Platform Team admins who own `scanner-preferences.yaml`.
> Developers running scans want [`../README.md`](../README.md) instead.
>
> **Common tasks:** [switch profile](#switching-profiles) · [which image runs](#image--optional-and-this-is-the-only-description-of-it) · [pin a component version](#how-to-pin-an-exact-component-version-platform-team-how-to) · [container scan target](#container-scanning-how-the-target-image-is-chosen)

`scanner-preferences.yaml` is the single admin-owned control point for this
skill. It is versioned, so changes go through an MR with Platform Team approval
(CODEOWNERS). Users never pick scanners — the skill reads this file each run.

Design principle for self-hosted / airgap environments: **everything is
declared here so the model only reads config, never guesses endpoints.** Every
URL, registry path and env var name is either written in this file or derived
from the CI component itself — nothing is inferred. `scripts/load-prefs.sh`
converts this file into shell variables and `RUN_*` flags; the model never
parses the YAML itself.

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
| `company` | Production preferences: internal GitLab mirror. Edit the placeholder `gitlab_instance` (and `component:` if your paths differ) — images come from your own catalogue's templates once you re-vendor. Airgap-safe. |

## Global `settings:` block

```yaml
settings:
  airgap: false               # shipped default; set true for internal-only environments
  container_runtime: auto     # auto (docker then podman) | docker | podman
  ca_bundle: ""               # host path to an internal CA PEM; mounted into every scanner
  pip_index_url: ""           # internal PyPI index the DS analyzer resolves from
  maven_settings: ""          # host path to settings.xml naming the internal mirror
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
  package_registries:         # URL TEMPLATES; all empty = upgrade check disabled
    npm: ""
    pypi: ""
    maven: ""
    go: ""
    auth_token_env: ""
  container_registry:
    user_env: CS_REGISTRY_USER      # env var NAMES holding registry creds
    password_env: CS_REGISTRY_PASSWORD
    base_repo: ""             # REF TEMPLATE with {image}/{tag}; may change a finding's status
    hardened_repo: ""         # REF TEMPLATE; suggestion-only, never changes a status
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
- **image_policy** — `follow-component` (default) tracks the CI component;
  `pinned` uses the category's `image:` verbatim, with no adoption and no pull
  check, for byte-identical reproducibility. What each policy does with (or
  without) an `image:` is the single table under
  [Per-category settings](#per-category-settings) — that table is the authority;
  nothing else here restates it.
- **ca_bundle** — host path to your internal HTTPS CA in PEM form. Bind-mounted
  read-only into every scanner container and exported inside it as
  `ADDITIONAL_CA_CERT_BUNDLE`, which is the variable the GitLab analyzers read;
  the dependency-scanning template forwards it into its own child processes.
  Empty (shipped default) mounts and exports nothing. Without it, an estate that
  terminates TLS on its own CA fails every scanner request in a way that reads
  like a network outage rather than a trust problem.
- **pip_index_url** / **maven_settings** — where the dependency-scanning analyzer
  *resolves packages from* while it builds the SBOM. Both of the component's own
  defaults (public PyPI, `./settings.xml`) only work with public internet, so on
  an airgapped host the analyzer hangs and reports a broken SBOM instead of
  saying it could not resolve anything. `maven_settings` is a host path,
  bind-mounted into the container; the Fortify maven build reads the same value.
  Exported as `APPSEC_PIP_INDEX_URL` (deliberately *not* `PIP_INDEX_URL`, which
  would repoint the developer's own `pip` in that terminal).
- **build_credentials** — env var **names** holding Artifactory credentials for the
  Fortify gradle build, defaulting to `ARTIFACTORY_USER` / `ARTIFACTORY_PASSWORD`
  (what the CI component itself reads, so most estates need no entry). Change them
  only if your environment already names its credentials differently — no secret is
  ever written to this file.
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
  still a vulnerability. Container-scanning findings are never probed against a
  *package* registry: those are OS packages in a base image, fixed by rebuilding on
  a newer base. They get `container_registry.base_repo` instead, below.

  Configuring at least one of these templates is also what switches the whole
  pre-loop probe on: `run-scan.sh` only runs `check-remediation.py` when
  `package_registries` contains a URL, so `base_repo` / `hardened_repo` are read on
  the same pass and not on one of their own.
- **container_registry.base_repo** — a **ref template** (`{image}`, `{tag}`), not a
  base URL, asking one question per base image: *does our registry carry this?*
  `{image}` is the Dockerfile `FROM` repository with registry and namespace stripped
  (`python`, `node`), because that is the question being asked.
  `scripts/container-target.sh` parses the `FROM` lines into `base-images.json` and
  `resolve-base-image.sh` probes each one. An `absent` verdict turns the
  container-scanning findings it blocks into `blocked_registry_gap` and TRIAGE.md
  §3b's base-image table; `unknown` (unreachable registry, auth failure, no runtime)
  changes nothing, for the same reason it does for packages. Empty = nothing probed.
- **container_registry.hardened_repo** — same template shape, **suggestion only**.
  A hardened image is a *different* image, not a newer tag: different libc, usually
  no shell and no package manager, a non-root UID. Its verdicts are filed under
  separate keys that no status decision reads, and the fix loop must never apply
  one — wire it into the fix path and the loop will "fix" builds by breaking them.
  A human decides. Empty = nothing suggested.

  Both are settable per profile, next to `gitlab_instance`, exactly as
  `auth_token_env` is; a profile value (including `""`) overrides the global one.
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

A category block is three keys. Both shipped profiles look exactly like this:

```yaml
categories:
  sast:
    component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
    version: ~latest          # ~latest OR an exact tag e.g. "25.2.0"
    enabled: true
```

The four categories are `sast`, `dependency_scanning`, `secret_detection`,
`container_scanning`.

### `image:` — optional, and this is the only description of it

`image:` is an **override, not the norm.** What actually runs is decided by
`resolve-image.sh` from the component template plus whatever `image:` you did or
did not declare:

| `image_policy` | No `image:` (shipped default) | `image:` declared |
|---|---|---|
| `follow-component` (default) | the template's ref is used whole, then pulled as an availability check. Unavailable ⇒ **the scan stops** and names the ref to mirror | `image:` supplies the registry and path, the template supplies the tag. Unavailable ⇒ warn and fall back to `image:` |
| `pinned` | nothing to run — configure `image:` | `image:` verbatim; no adoption, no pull check |

Omitting `image:` is the intended steady state once your catalogue's templates
name a registry you can reach — which means vendoring snapshots **from your own
instance** (MIGRATION.md "Re-vendor"). Declare `image:` when your mirror path
differs from the template's, or as the fallback for a tag you have not mirrored.

**The JDK variant (Fortify) is automatic — there is nothing to configure.** A Fortify tag
is `<version>-<variant>`, where the variant is the JDK that compiles your code
(`jdk17-review` | `jdk21-review`) and the component always defaults to `jdk17-review`.
Each run reads the repository's own build files and picks for you:

```
INFO: [Fortify SCA] Project targets Java 21; selecting jdk21-review
```

`scripts/detect-java-release.sh` reads `maven.compiler.release|source|target`,
`java.version` and the compiler plugin's `<release>/<source>/<target>` from every
`pom.xml`, and `JavaLanguageVersion.of(N)`, `jvmToolchain(N)` and
`source|targetCompatibility` from every `*.gradle[.kts]` — every, not just
`build.gradle`, so a `buildSrc` convention plugin is covered. A version referenced
by name (`JavaLanguageVersion.of(javaVersion)`) is resolved from `gradle.properties`. It takes the **highest**
release found anywhere — a JDK builds its own release and every earlier one, never a
later one — and `scripts/select-jdk-variant.sh` maps it to the **smallest offered
variant that can still compile it**. Which variants exist is read from the component
**as resolved that run**, not hardcoded and not gated on this repo: publish
`jdk25-review` and the next developer scan uses it for Java 22+ projects with no MR
here — the same way `version: ~latest` already rolls out a new component version.
Retire `jdk17-review` and it stops being selected just as directly. The checked-in
`scanners/fortify-sast.contract` is the offline fallback for runs that cannot reach
the catalogue; `check-drift` still reports the change either way. If nothing offered
is new enough, the highest one runs and the scan says so. Generated copies under
`target/` and `build/` are ignored. `.tool-versions`, `.sdkmanrc` and `.java-version` are
deliberately **not** read: they pin a developer's local toolchain, which is often newer
than what the build targets, and guessing high breaks builds that guessing low does not.

Precedence, highest first:

| Source | When it wins |
|---|---|
| `FORTIFY_VARIANT=jdk21-review` in the environment | always — the escape hatch for a repository the detector reads wrongly |
| detected from the build files | whenever a release is found |
| the variant in your `image:` tag | no release could be detected |
| the component's default (`jdk17-review`) | nothing else said anything |

Detection is a preference, never a requirement: if your registry does not carry the
selected variant, the scan **warns and runs the component's default** rather than
failing. Non-Java projects are unaffected — no release is detected, so nothing changes.

Dependency scanning's `resolution_job_variant` (`openjdk17|openjdk21`) has the same shape
but is not reachable locally — the skill runs the analyzer directly and never runs a
resolution job.

An image that can be neither derived nor configured **stops the scan with a
non-zero exit**. It is never guessed and the scanner is never skipped: a skipped
scanner reads as a clean result for a category that never ran.

The pull check is skipped under `--dry-run`, which resolves the same candidate
without touching the network.

- **`runner:` is optional too** — each category has one shipped runner and gets it
  by default. Declare it to point at a custom or swapped runner; `check-drift` uses
  the name to find the sibling `<runner>.contract`. `runner: none` = CI-only, no
  local run.
- **`version:` controls catalog resolution** — two modes:
  - `~latest` (default) — `catalog.sh` resolves the highest stable release tag
    each run and uses it. Keeps you current without manual bumps.
  - Exact tag (e.g. `"25.2.0"`) — pins the component version used for image
    derivation, drift comparison and AGENTS.md lookup. If a newer stable tag
    exists, `catalog.sh` prints
    `ADVISORY: <component> pinned <X>, newer stable <Y> available` — surface it
    to the admin.
- **`component:` is resolved every run** for four things: the image the scan runs
  (above), the component's usage guide (README, cached under
  `.appsec-results/catalog/`), the agent-oriented reference (AGENTS.md, also
  cached), and drift — `DRIFT:` when a declared `image:` differs from the
  component's, `CONTRACT-DRIFT:` when its inputs or reports moved.

## How to pin an exact component version (Platform Team how-to)

1. Decide the tag to pin (e.g. `25.2.0` for fortify-sast).
2. In the relevant category block, set `version: "25.2.0"`.
3. Refresh the vendored snapshot so offline fallback and image derivation stay
   current: see UPDATE-GUIDE.md Scenario 6.
4. Only if this category also declares an `image:`, move it to the matching tag —
   otherwise the pinned template supplies it.
5. Open an MR. The ADVISORY line on future runs reminds you when a newer
   stable tag is available.

## Category notes

- **sast** — Fortify SCA multi-language scanner. Language auto-detected from
  project files (gradle > maven > python > javascript > go); set
  `FORTIFY_LANGUAGE` to override. The FPR output
  (`.appsec-results/fortify-sast.fpr`) contains the full severity breakdown; the
  local summary shows total vulnerability count.
- **dependency_scanning** — generates an **SBOM** locally
  (`gl-sbom-*.cdx.json`). The skill passes `GITLAB_FEATURES=dependency_scanning`
  to mirror the licensed CI environment. A lock file is required; plain manifests
  are skipped.

  **GitLab-matched dependency results cannot be produced locally, by anything.**
  GitLab matches the SBOM server-side behind an API that accepts only a real
  `CI_JOB_TOKEN`, so no local runner — this skill, `glci`, `gitlab-ci-local`,
  `gitlab-runner exec` — can obtain them. Please do not re-litigate this by
  wiring in another runner; the blocker is the token, not the runner.

  An SBOM alone normalizes to zero findings, which would read as "scanned,
  clean". So `scanners/sbom-vuln-scan.sh` matches it offline with the Trivy
  bundled in the *container-scanning* image, against that image's baked advisory
  DB. **Those findings are Trivy's, not GitLab's** — different advisory source,
  so they will not match the post-push Vulnerability Report in content or count.
  They exist to give the fix loop real `fixed_version`s to work with and to give
  developers a pre-push signal. Tell users which one they are looking at. If that
  pass cannot run (container scanning disabled, or `--only dependency_scanning`
  with no CS image), the category is recorded as a coverage skip, never as clean.
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

In registry mode the run also exports `CS_DOCKERFILE_PATH` when a Dockerfile is
present. The component declares that input, and it is what makes GTCS emit its
own "upgrade the base image to X" remediation; nothing set it before, so that
remediation never ran locally.

If a local build fails because a `FROM` base image cannot be pulled from your
internal registry, the skill tells you to run `<runtime> login <registry-host>`
(or set the `container_registry` credential env vars) and points the Dockerfile
`FROM` at the internal mirror. Any other build error prints
"Submit a Jira ticket under others".

## Per-run env overrides (users)

`CS_IMAGE`, `DOCKERFILE`, `FORTIFY_LANGUAGE`, `MAVEN_SETTINGS`, and the image env
vars (`FORTIFY_SAST_IMAGE`, `GITLAB_DS_IMAGE`, `SECRET_DETECTION_IMAGE`,
`GITLAB_CS_IMAGE`) override for a single run. They change *where images come
from*, *what is scanned*, or *which Fortify language is used* — never *which
scanner runs* (that is this file's job). An already-exported `MAVEN_SETTINGS`
wins over `settings.maven_settings` so the shipped empty default cannot unset a
working export mid-session.

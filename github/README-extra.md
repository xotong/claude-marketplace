## Self-hosted-model tier

For Claude Code running against a self-hosted model (e.g. Qwen), which lacks
Claude Code's own built-ins (plan mode, `/code-review`, `/security-review`)
and may be deployed fully airgapped. `essentials-self-hosted` ships
copy-based skills (TDD, debugging, planning, feature-dev, PR review) that
stand in for what the Claude tier gets from built-ins, and every plugin in
this tier is chosen to keep working offline with a non-Anthropic model.

Install `essentials-self-hosted` to get started:
```
/plugin install essentials-self-hosted@platform-claude-marketplace
/reload-plugins
```
Gives you: TDD, systematic debugging, planning, git worktrees, 7-phase
feature development, and 6-agent parallel PR review — copy-based skills
that stand in for the Claude-tier built-ins.

| Plugin | What it gives you |
|---|---|
| **essentials-self-hosted** | Start here. Curated starter pack: superpowers (TDD, debugging, planning, git worktrees), 7-phase feature development, and 6-agent parallel PR review — all in one install. The old copy-based `essentials`, renamed and unchanged. |
| **superpowers** | 14 core developer skills (already in essentials-self-hosted — install for the full library). |
| **anthropic-feature-dev** | 7-phase feature dev workflow (already in essentials-self-hosted). |
| **anthropic-pr-review** | 6-agent parallel PR review (already in essentials-self-hosted). |
| **agent-skills** | 24 production-engineering skills from Addy Osmani (TDD, API design, security hardening, perf). |
| **compound-engineering** | 38 skills + 50 specialised review agents for compound AI workflows. |
| **gstack** | 54 productivity skills: QA, browser automation, design, production safety gates. |
| **ruflo** | 33 swarm/memory/AgentDB/SPARC skills for AI orchestration. |
| **getshitdone** | 66 `/gsd` slash commands for the full Plan→Execute→Verify lifecycle. |

**Check for duplicate skills:** `essentials-self-hosted` bundles
`superpowers`, `anthropic-feature-dev`, and `anthropic-pr-review` content
together. If you install any of those individually on top of
`essentials-self-hosted`, some skills will appear twice in `/skills`. This
is harmless — both copies are identical — but to avoid it, install *either*
`essentials-self-hosted` *or* the individual component plugins, not both.

**Choosing a tier (for contributors):** put a new plugin under
`plugins/self-hosted/<source-name>/` if it is a stand-in for a Claude Code
built-in (planning, feature-dev, PR review, the TDD/debugging workflow
essentials-self-hosted covers) or if it must keep working fully airgapped
against a non-Anthropic model. Put everything else under
`plugins/<source-name>/` (Claude tier) — including anything that relies on
Claude-specific behavior, the Anthropic API, or a licence that restricts it
to Claude Code/Anthropic products. When in doubt: would this plugin make
sense for someone running Qwen with no internet? If not, it's Claude tier.

---

## AppSec airgap setup

The `appsec-scan` skill runs security scanners locally against a configurable
GitLab CI/CD Catalog. It is built for airgapped networks: it talks only to your
**internal** GitLab and image registry, and keeps working with no internet at
all. This section is for the **skill admin** who tailors it to your environment.
Everything is set in one file — `plugins/appsec/skills/appsec-scan/config/scanner-preferences.yaml`
— so a self-hosted model only reads config and never guesses endpoints. Full
schema reference: `config/PREFERENCES.md` next to it.

### What the skill actually requires

**Hard dependencies (present on any dev machine — nothing to mirror):**
`docker` **or** `podman`, `bash`, `git`, and coreutils. The skill detects the
runtime first and stops with a clear message if none is found.

**Missing tooling degrades gracefully — never a hard failure:** `jq` (severity
summary; see below), `curl` (only for live catalog; falls back to vendored
snapshots), `unzip` (only for Fortify FPR summaries), `glab`
(only for the optional end-of-run MR offer). `python3` is **not** required at
runtime.

**Broken configuration does not.** A credential your registry or GitLab instance
*refuses* stops the work it blocks, prints a `CONFIG-ERROR:` naming the setting
to fix, and exits non-zero — no fallback, no alternative method tried. Only an
unreachable host degrades. The two used to be indistinguishable, which meant a
misconfigured mirror produced a scan that read like a result.

### Step 1 — Mirror the analyzer images to your registry

Mirror these four images into your internal JFrog (their scan rules and
vulnerability DBs are baked in — **scanning itself needs no network inside the
containers**). The one exception is the Fortify Python arm: if you configure
`settings.python_runtime`, it fetches uv, an interpreter and the project's
packages **from your mirror** to resolve imports. Leave it unset and the scan
degrades to stdlib-only resolution and says so — it never reaches the public
internet to close the gap:

```
registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sca:25.2.0-jdk17-review  → <your-registry>/security/fortify-sca:25.2.0-jdk17-review
registry.gitlab.com/security-products/secrets:7                                                          → <your-registry>/security/secrets:7
registry.gitlab.com/security-products/dependency-scanning:2                                              → <your-registry>/security/dependency-scanning:2
registry.gitlab.com/security-products/container-scanning:8                                               → <your-registry>/security/container-scanning:8
```

Then set each category's `image:` in the `company` profile to the mirrored path.
`image:` is what actually runs (admin-pinned); the `component:` path is resolved
each run only for its usage guide and a drift advisory that tells you when to
bump the pin.

### Step 2 — Point the profile at your GitLab and turn on airgap

```yaml
settings:
  airgap: true                 # internal endpoints only; refuses the catalog profile (gitlab.com)
  container_runtime: auto      # auto-detect docker or podman
  catalog:
    mode: online               # resolve customized components live against your GitLab
    auth_token_env: ""         # see Step 4
profiles:
  company:
    gitlab_instance: https://gitlab.your-company.internal
    categories:
      sast:
        component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
        version: "25.2.0"
        image: <your-registry>/security/fortify-sca:25.2.0-jdk17-review
        runner: fortify-sast.sh
        enabled: true
      # …dependency_scanning, secret_detection, container_scanning…
```

`airgap: true` also works alongside internet-connected sites — flip it to
`false` (or use the shipped `catalog` profile) when you *do* have internet,
e.g. for validation against gitlab.com. Same skill, both worlds.

### Step 3 — jq (optional, for the severity summary)

If `jq` is on the dev machine, nothing to do. If not, host the binary in JFrog
and point the skill at it — `{os}` and `{arch}` are filled from `uname`, so one
URL serves a mixed fleet:

```yaml
settings:
  jq:
    install_url: https://jfrog.your-company.internal/artifactory/tools/jq/{os}/{arch}/jq
```

Leave it empty to simply show `UNKNOWN` counts when `jq` is absent — the scan
still runs.

### Step 4 — Catalog authentication

Leave `auth_token_env` **empty** if your instance serves the ci-catalogue
projects to unauthenticated API reads. If it does not, create a `read_api`
Personal Access Token, put it in an env var, and name that var in the config:

```yaml
settings:
  catalog:
    auth_token_env: GITLAB_READ_TOKEN     # the skill reads $GITLAB_READ_TOKEN
```

Naming a variable makes it **required**: preflight fails fast if it is unset, and
a token the instance rejects is a `CONFIG-ERROR:` that stops the scan. Neither
falls through to the vendored snapshots, because a run that quietly used a
snapshot would look exactly like a live check that passed. An instance that is
merely *unreachable* does fall back to `reference/catalog/` — that is the airgap
guarantee, and it is reported as `[offline-fallback]`. Refresh those snapshots
periodically per `UPDATE-GUIDE.md` (Scenario 6).

### Step 5 — Container scanning

GTCS scans a **registry** image, so the skill resolves the target two ways
automatically:

- **Already-built image** — set `CS_IMAGE=<image:tag>` (pushed to your
  registry) and the real `gtcs scan` runs, using the credentials named in
  `settings.container_registry`.
- **Local shift-left** — with no `CS_IMAGE` but a `Dockerfile` present, the
  skill builds and saves the image locally and scans the tarball with the
  analyzer image's bundled Trivy — fully offline, no registry, no root. If a
  `FROM` base can't be pulled, it prompts you to `docker login` / `podman login`
  your registry or set the credential env vars.

### Verifying offline behavior

With the network unplugged, `catalog.sh` prints `[offline-fallback]` and the
scan proceeds from vendored snapshots. If a selected scanner produces no report
(e.g. an image failed to pull), the summary says **"Results are incomplete —
this is NOT an all-clear"** rather than a false green.

Admin setup steps live in `plugins/appsec/skills/appsec-scan/MIGRATION.md`, vendored with the plugin.

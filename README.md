# Claude Code Marketplace

The Platform Team's Claude Code plugin marketplace. Add it once, install the starter bundle, and you're set. Team-specific skills live in each team's own marketplace (see "For teams").

## Get started (one-time setup)

### Step 1 — Add the marketplace

In any Claude Code session, run:

```
/plugin marketplace add https://gitlab.example.com/platform-engineering/skillshub/claude-marketplace.git
```

Claude Code will clone the catalog and register it as `platform-claude-marketplace`. You only need to do this once per machine.

### Step 2 — Install skills

**Start here:**
```
/plugin install essentials@platform-claude-marketplace
/reload-plugins
```
Dependency-only bundle — installs `appsec` (security scanning), `code-quality`, `claude-security` (deep vulnerability hunt with patches), `security-guidance` (edit-time warnings and an end-of-turn security review) and the Python/TypeScript/Go/Java language servers (each needs its binary on PATH; a missing one is skipped). Planning and review come from Claude Code's built-ins (plan mode, `/code-review`, `/security-review`).

Already installed `security-guidance` from `claude-plugins-official`? Uninstall it (`/plugin uninstall security-guidance@claude-plugins-official`): otherwise every review runs twice, and the upstream copy cannot reach the API through Zscaler. Its reviews use Opus 4.7 by default and count against your own usage; the Platform Team can pick a cheaper model for everyone with `SECURITY_REVIEW_MODEL` in managed settings.

**Browse all available plugins:**
```
/plugin marketplace list platform-claude-marketplace
```

**Install any plugin by name:**
```
/plugin install <plugin-name>@platform-claude-marketplace
/reload-plugins
```

Available plugins: `essentials`, `appsec`, `code-quality`, `claude-security`, `security-guidance`, `pyright-lsp`, `typescript-lsp`, `gopls-lsp`, `jdtls-lsp`, `code-modernization`, `skill-scanner`, `anthropic-dev-skills`, `obsidian`, `anthropic-hookify`, `frontend-design`, `ponytail`, `trailofbits-skills`

**Your team's private skills:**

Team skills are **not** listed in this marketplace — each team hosts its own standalone marketplace in their private skills repo. Add it separately:
```
/plugin marketplace add https://gitlab.example.com/platform-engineering/skillshub/<team-name>-skills.git
```

After adding the team marketplace, install from it the same way:
```
/plugin install <plugin-name>@<team-marketplace-name>
/reload-plugins
```

Ask your team lead for the exact repo URL and plugin names. Team skill names and descriptions are private to that repo.

### Step 3 — Verify and manage your install

**See all installed plugins and their skill counts:**
```
/plugin list
```

**See every loaded skill across all installed plugins:**
```
/skills
```

`essentials` is dependency-only — it installs `appsec`, `code-quality`, `claude-security`, `security-guidance` and the four LSP plugins each exactly once, so no duplicate skills show up in `/skills`.

**Uninstall a plugin:**
```
/plugin uninstall <plugin-name>
/reload-plugins
```

**Update all plugins to latest:**
```
/plugin update
/reload-plugins
```

If a plugin is missing after install, re-run the install command.

> **Skill security scan:** MRs and pushes to `main` run SkillSpector (static-only, no CI/CD variables required) via the `platform-engineering/ci-catalogue/skillspector` component. See "Skill security scan — CI safety gate" below.

---

## Plugins

This catalog is for developers running Claude Code against Anthropic's Claude models. Claude Code's own built-ins (plan mode, `/code-review`, `/security-review`) already cover planning and review, so `essentials` only adds what those built-ins don't: security scanning and review, code quality, and language-server code intelligence.

| Plugin | What it gives you |
|---|---|
| **essentials** | Start here. Dependency-only bundle — installing it installs `appsec`, `code-quality`, `claude-security`, `security-guidance` and the four LSP plugins. Planning and review come from Claude Code's built-ins. |
| **appsec** | Catalog-driven security scanning: 4 components from the private GitLab CI/CD Catalog (Fortify SCA SAST, Dependency Scanning SBOM, Secret Detection, Container Scanning) with per-component version pinning, fix loop + triage plan; OWASP WSTG DAST sim; and a `security-options` routing skill for anything the first two don't cover. |
| **code-quality** | Lint gate, API design enforcement, OpenAPI spec generation, doc co-authoring. |
| **claude-security** | [Vendored: Anthropic] Deep vulnerability scan of your own code with a challenge/verify loop, turning surviving findings into agent-verified patches. Proprietary Anthropic licence — internal use only, solely with Claude Code/Anthropic products, and excluded from the public GitHub mirror. |
| **security-guidance** | [Vendored: Anthropic] Pattern-based warnings on edits + LLM-powered diff review on Stop + an agentic commit reviewer. In essentials. Needs internet and the Anthropic API. |
| **pyright-lsp** / **typescript-lsp** / **gopls-lsp** / **jdtls-lsp** | [Vendored: Anthropic] Language servers for Python/TS-JS/Go/Java code intelligence. In essentials. Each needs its language-server binary on `PATH` — a one-time install; until then the server is skipped and `/plugin` → Errors names the binary. |
| **code-modernization** | [Vendored: Anthropic] Guided legacy-codebase modernization: assessment, business-rule mining, plan, and a verified upgrade/rewrite/rebuild. Works offline. |
| **skill-scanner** | [Vendored: getsentry/skills] Scans a skill or plugin for prompt-injection and supply-chain risk before you install it. Works offline. |
| **anthropic-dev-skills** | Claude API, MCP builder, webapp testing (4 skills). |
| **obsidian** | 5 Obsidian knowledge management skills. |
| **anthropic-hookify** | Git hooks framework + writing-rules skill. |
| **frontend-design** | Frontend design patterns skill. |
| **ponytail** | Lazy-senior-dev mode: simplest solution that works (YAGNI, stdlib first) + over-engineering review/audit. |
| **trailofbits-skills** | 33 Trail of Bits security skills: audit workflows, Semgrep/CodeQL authoring, fuzzing handbook. Some skills expect locally installed tools (semgrep, codeql, fuzzers). |

---

## Plugin catalog

| Plugin | Type | What's inside | Not-malicious confidence¹ |
|---|---|---|---|
| `essentials` | Platform Team | Dependency-only bundle → `appsec` + `code-quality` + `claude-security` + `security-guidance` + 4 LSPs | n/a (no content of its own) |
| `appsec` | Platform Team | Catalog-driven security scanning: 4 components from the private GitLab CI/CD Catalog (Fortify SCA SAST, Dependency Scanning SBOM, Secret Detection, Container Scanning) with per-component version pinning (~latest or exact tag), fix loop + triage plan; OWASP WSTG DAST sim; `security-options` routing skill | 96% |
| `code-quality` | Platform Team | lint-and-validate + api-design-principles + openapi-spec-generation + doc-coauthoring | 97% |
| `claude-security` | Vendored (Anthropic) | Deep vulnerability scan + challenge/verify loop + agent-verified patches. Proprietary licence — Claude models only. | not yet scored² |
| `security-guidance` | Vendored (Anthropic) | Pattern warnings on edit + LLM diff review on Stop + agentic commit reviewer. Needs internet + Anthropic API. | not yet scored² |
| `pyright-lsp` / `typescript-lsp` / `gopls-lsp` / `jdtls-lsp` | Vendored (Anthropic) | Language servers for Python / TS-JS / Go / Java. Need the LSP binary on `PATH`. | not yet scored² |
| `code-modernization` | Vendored (Anthropic) | Guided legacy modernization: assessment, rule mining, plan, verified rewrite. Offline. | not yet scored² |
| `skill-scanner` | Vendored (getsentry/skills) | Scans a skill/plugin for prompt-injection and supply-chain risk before install. Offline. | not yet scored² |
| `anthropic-dev-skills` | Vendored (Anthropic) | claude-api, mcp-builder, webapp-testing, dual-mode (4 skills) | 97% |
| `obsidian` | Vendored (Steph Ango) | obsidian-markdown, bases, CLI, json-canvas, defuddle (5 skills) | 96% |
| `anthropic-hookify` | Vendored (Anthropic) | Git hooks framework + writing-rules skill + /hookify command | 87% |
| `frontend-design` | Vendored (Anthropic) | Frontend design patterns skill | 98% |
| `ponytail` | Vendored (Dietrich Gebert) | 6 skills: lazy-senior-dev mode, over-engineering review/audit, debt ledger + session hooks (needs `node`) | 92% |
| `trailofbits-skills` | Vendored (Trail of Bits) | 33 security skills: audit workflows, Semgrep/CodeQL authoring, SARIF, supply-chain, fuzzing handbook | 97% |

> ¹ LLM-as-judge confidence (0–100%) that the plugin contains no malicious content, scanned 2026-07-05 per plugin against the CI scanner's five risk categories (prompt injection, data exfiltration, destructive commands, embedded secrets, scope creep) by Claude agents (Fable 5 for obsidian/frontend-design/ponytail/trailofbits-skills; Sonnet 4.6 for the rest). Higher = cleaner. Scores reflect risk indicators found, not overall quality. Separately, CI runs SkillSpector (static, report-only) on every MR. Full findings are in PR history.
> ² Vendored in this split; not yet covered by the 2026-07-05 scan baseline. SkillSpector scans them in CI (report-only); a confidence score will be added to this table on the next scan pass.

> All content is vendored at a fixed commit — no runtime network calls to upstream repos required by the marketplace itself. Individual skills that need network or local tools are flagged in `VENDORED.md` and the plugin descriptions. See `VENDORED.md` for commit SHAs and license notes.

---

## For teams: create your own private marketplace

Team skills live in your own private repo — **not** in this central catalog. This means:

- Plugin names and skill descriptions are never visible to other teams
- You control your own release cadence
- You can offer multiple granular plugins (e.g. one per domain) so developers install only what they need
- You never need Platform Team approval to add or update your own skills

### Step 1 — Create and structure your repo

Create a new project under the `skillshub` GitLab group named `<team-name>-skills`.

> **Set the project visibility to Private.** The `skillshub` group is internal (visible to everyone signed in to this GitLab) — private projects within it are hidden from non-members. Add your team members directly to the project to keep it invisible in the group listing.

Structure:

```
<team-name>-skills/
  .claude-plugin/
    marketplace.json        ← your team's marketplace catalog (lists your plugins)
  plugins/
    <plugin-name>/
      .claude-plugin/
        plugin.json         ← required per plugin
      skills/
        <skill-name>/
          SKILL.md          ← required
          supporting-doc.md ← optional
  .gitlab-ci.yml            ← required: include the SkillSpector component
```

### Step 2 — Set up your marketplace catalog

Your repo is its own marketplace. Each plugin is an independently installable unit — create as many as makes sense for your team.

**`.claude-plugin/marketplace.json` example:**
```json
{
  "name": "<team-name>-skills",
  "version": "1.0.0",
  "description": "Skills for the <team-name> team.",
  "owner": { "name": "<Team Name>" },
  "plugins": [
    {
      "name": "<plugin-name>",
      "source": "./plugins/<plugin-name>",
      "version": "1.0.0",
      "description": "Brief description of what this plugin does.",
      "author": { "name": "<Team Name>" }
    }
  ]
}
```

**`plugins/<plugin-name>/.claude-plugin/plugin.json` minimum:**
```json
{
  "name": "<plugin-name>",
  "version": "1.0.0",
  "description": "Brief description.",
  "author": { "name": "<Team Name>" }
}
```

**`.gitlab-ci.yml` minimum:**
```yaml
include:
  - component: $CI_SERVER_FQDN/platform-engineering/ci-catalogue/skillspector/skillspector@~latest
```

No CI/CD variables required — SkillSpector is static-only.

### Step 3 — Write a skill

```markdown
---
name: <skill-name>
description: >
  What this skill does and when to use it. Include specific trigger phrases:
  "Use when the user says 'deploy to staging', 'promote to prod', or asks
  to run the release pipeline." Include anti-triggers if there is ambiguity:
  "Do NOT activate for local test runs."
---

# Skill Title

## What to do

1. Step one — be explicit.
2. Step two.

## What NOT to do

- No destructive actions without explicit user confirmation.
- Do not call external services unless the user has authorised it.
```

**Trigger description tips:**
- Include 3–5 example trigger phrases in quotes
- Keep it under 200 words — Claude truncates long descriptions
- Be specific: vague descriptions cause false positives and missed triggers

### Step 4 — Distribute to your team

Share the repo URL with your team. Developers add your marketplace directly:

```
/plugin marketplace add https://gitlab.example.com/platform-engineering/skillshub/<team-name>-skills.git
```

Then install individual plugins from it:

```
/plugin install <plugin-name>@<team-name>-skills
/reload-plugins
```

> **No MR to this repo needed.** Your marketplace is entirely self-contained. You do not need Platform Team approval to publish or update your team's skills.

### Step 5 — Contribute a skill back (optional)

If your team builds a skill that would benefit the whole org, you can propose it for the Platform Team catalog. Open an MR against **this** repo using the **"Add Vendored Plugin"** MR template. The Platform Team will review and vendor it if approved.

---

## For contributors: adding and updating vendored plugins

This section covers adding or updating **vendored upstream content** in the Platform Team catalog. Team-specific skills belong in the team's own private repo — see "For teams" above.

Each upstream source has its own plugin directory under `plugins/<source-name>/`. The CI scanner runs across all plugin directories automatically.

### Adding a new upstream source

1. Clone the upstream repo:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   ```

2. Create a new plugin directory `plugins/<source-name>/` and copy content:
   ```bash
   mkdir -p plugins/<source-name>/.claude-plugin
   mkdir -p plugins/<source-name>/skills
   cp -r /tmp/<source-name>/skills/. plugins/<source-name>/skills/
   # Add agents/ and commands/ similarly if the source has them
   ```

3. Write `plugins/<source-name>/.claude-plugin/plugin.json`:
   ```json
   {
     "name": "<source-name>",
     "version": "1.0.0",
     "description": "[Vendored: <upstream-url>] Brief description of what this plugin provides.",
     "author": { "name": "Platform Team" },
     "keywords": ["relevant", "tags"]
   }
   ```

4. If broadly useful for everyone: add its name to `dependencies` in `plugins/essentials/.claude-plugin/plugin.json`.

5. Register in `.claude-plugin/marketplace.json` — add an entry to the `plugins` array, `source` pointing at `./plugins/<source-name>`.

6. Record provenance in `VENDORED.md` (upstream URL, commit SHA, date, license).

7. Open an MR using the **"Add Vendored Plugin"** MR template. Platform Team is a required approver.

### Updating an existing upstream source

1. Clone the upstream at the new commit:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   ```

2. Replace the content in the plugin directory:
   ```bash
   rm -rf plugins/<source-name>/skills/*
   cp -r /tmp/<source-name>/skills/. plugins/<source-name>/skills/
   # Also update essentials if it bundles content from this source
   ```

3. Update the SHA and date in `VENDORED.md`.

4. Bump `version` in `plugins/<source-name>/.claude-plugin/plugin.json` and open an MR.

Platform Team is a required approver (CODEOWNERS).

---

## Repo layout

```
.claude-plugin/marketplace.json        Central catalog — Platform Team only
.gitlab-ci.yml                         CI: JSON validation, shellcheck, appsec drift check, appsec tests, SkillSpector scan
ci/                                    check-appsec-drift.py, publish-github.sh
CODEOWNERS                             Write-access rules with [Section][1] approval counts
VENDORED.md                            Upstream SHAs, license notes, update cadence
CLAUDE.md                              Project context for contributors

plugins/                               For Claude Code against Claude models
  essentials/                          Dependency-only bundle (Platform Team maintained)
    .claude-plugin/plugin.json         dependencies: appsec, code-quality, claude-security, security-guidance, 4 LSPs
  appsec/                              Platform Team — appsec-scan, appsec-dast-sim, security-options
  code-quality/                        Platform Team — 4 code/doc quality skills
  claude-security/                     Vendored: Anthropic — deep vuln scan + patch loop (Claude models only)
  security-guidance/                   Vendored: Anthropic — edit-time + end-of-turn LLM review (internet/API)
  pyright-lsp/                         Vendored: Anthropic — Python language server
  typescript-lsp/                      Vendored: Anthropic — TypeScript/JS language server
  gopls-lsp/                           Vendored: Anthropic — Go language server
  jdtls-lsp/                           Vendored: Anthropic — Java language server
  code-modernization/                  Vendored: Anthropic — guided legacy modernization
  skill-scanner/                       Vendored: getsentry/skills — pre-install skill/plugin scanner
  anthropic-dev-skills/                Vendored: anthropics/skills (4 skills)
  obsidian/                            Vendored: kepano/obsidian-skills (5 skills)
  anthropic-hookify/                   Vendored: anthropics/claude-plugins-official
  frontend-design/                     Vendored: anthropics/skills (1 skill)
  ponytail/                            Vendored: DietrichGebert/ponytail (6 skills + mode hooks)
  trailofbits-skills/                  Vendored: trailofbits/skills (33 skills, curated subset)

.gitlab/
  merge_request_templates/
    add-vendored-plugin.md
```

---

## Governance

| Path | Who can merge | Minimum approvals |
|---|---|---|
| `.claude-plugin/marketplace.json` | Platform Team | 1 |
| `plugins/essentials/` | Platform Team | 1 |
| `plugins/appsec/` | Platform Team | 1 |
| `plugins/code-quality/` | Platform Team | 1 |
| `plugins/claude-security/` | Platform Team | 1 |
| `plugins/<vendored-source>/` | Platform Team | 1 |
| `CODEOWNERS`, `VENDORED.md`, `ci/`, `.gitlab-ci.yml` | Platform Team | 1 |

Team skill content lives in separate private repos and is governed entirely by the team — no entry in this table covers it. The Platform Team has no read access to those repos unless explicitly added.

---

## Skill security scan — CI safety gate

Every team skills repo should include SkillSpector (NVIDIA, Apache-2.0), a static-only skill security scanner — no LLM calls, no CI/CD variables required.

```yaml
# .gitlab-ci.yml in your skills repo — this is the complete config
include:
  - component: $CI_SERVER_FQDN/platform-engineering/ci-catalogue/skillspector/skillspector@~latest
    inputs:
      scan_root: plugins
      scope: changed

# Pin to an exact version instead of ~latest:
#   - component: $CI_SERVER_FQDN/platform-engineering/ci-catalogue/skillspector/skillspector@<VERSION>
```

Currently report-only (`fail_on: none`) while SkillSpector's accuracy is under review — it will not fail your pipeline. MR pipelines scan only changed skills (`scope: changed`); set the `SKILLSPECTOR_SCOPE=all` runtime variable (or `scope: all`) for a full scan.

---

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

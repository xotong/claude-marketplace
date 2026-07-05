# Claude Code Marketplace

Central plugin marketplace. One URL to configure; all team and platform skills flow from here.

| Plugin | What it gives you |
|---|---|
| **essentials** | Start here — TDD, debugging, planning, feature dev, PR review in one install. |
| **appsec** | Catalog-driven security scanning: admin preference profiles (Fortify or GitLab SAST, GitLab dependency/secret/container scanning), CI/CD Catalog versions resolved every run, fix loop + triage plan — plus OWASP WSTG DAST sim. |
| **code-quality** | Lint gate, API design enforcement, OpenAPI spec generation, doc co-authoring. |
| **superpowers** | 14 core developer skills (already in essentials — install for the full library). |
| **compound-engineering** | 38 skills + 50 specialised review agents for compound AI workflows. |
| **gstack** | 54 productivity skills: QA, browser automation, design, production safety gates. |
| **ruflo** | 33 swarm/memory/AgentDB/SPARC skills for AI orchestration. |
| **getshitdone** | 66 `/gsd` slash commands for the full Plan→Execute→Verify lifecycle. |
| **anthropic-dev-skills** | Claude API, MCP builder, webapp testing (already in essentials → feature-dev). |
| **obsidian** | 5 Obsidian knowledge management skills. |
| **anthropic-feature-dev** | 7-phase feature dev workflow (already in essentials). |
| **anthropic-pr-review** | 6-agent parallel PR review (already in essentials). |
| **anthropic-hookify** | Git hooks framework + writing-rules skill. |
| **frontend-design** | Frontend design patterns skill. |
| **ponytail** | Lazy-senior-dev mode: simplest solution that works (YAGNI, stdlib first) + over-engineering review/audit. |
| **agent-skills** | 24 production-engineering skills from Addy Osmani (TDD, API design, security hardening, perf). |
| **trailofbits-skills** | 33 Trail of Bits security skills: audit workflows, Semgrep/CodeQL authoring, fuzzing handbook. |

---

## For tenants: one-time Claude Code setup

### Step 1 — Add the marketplace

In any Claude Code session, run:

```
/plugin marketplace add https://gitlab.company.com/skillshub/claude-marketplace.git
```

Claude Code will clone the catalog and register it as `platform-claude-marketplace`. You only need to do this once per machine.

### Step 2 — Install skills

**Start here (recommended for everyone):**
```
/plugin install essentials@platform-claude-marketplace
/reload-plugins
```

Gives you: TDD, systematic debugging, planning, git worktrees, 7-phase feature development, and 6-agent parallel PR review.

**Add security scanning (recommended for all developers):**
```
/plugin install appsec@platform-claude-marketplace
/plugin install code-quality@platform-claude-marketplace
/reload-plugins
```

**Browse all available plugins:**
```
/plugin marketplace list platform-claude-marketplace
```

**Install any plugin by name:**
```
/plugin install <plugin-name>@platform-claude-marketplace
/reload-plugins
```

Available plugin names: `essentials`, `appsec`, `code-quality`, `superpowers`, `compound-engineering`, `gstack`, `ruflo`, `getshitdone`, `anthropic-dev-skills`, `obsidian`, `anthropic-feature-dev`, `anthropic-pr-review`, `anthropic-hookify`, `frontend-design`

**Your team's private skills:**

Team skills are **not** listed in this marketplace — each team hosts its own standalone marketplace in their private skills repo. Add it separately:
```
/plugin marketplace add https://gitlab.company.com/skillshub/<team-name>-skills.git
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

**Check for duplicate skills:**
`essentials` bundles `superpowers`, `anthropic-feature-dev`, and `anthropic-pr-review` content together. If you install any of those individually on top of `essentials`, some skills will appear twice in `/skills`. This is harmless — both copies are identical — but to avoid it, install *either* `essentials` *or* the individual component plugins, not both.

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

> **Need a `LITELLM_API_KEY`?** This key is needed if your team runs the skill scanner CI job. If you don't have one, raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

---

## Plugin catalog

| Plugin | Type | What's inside | Not-malicious confidence¹ |
|---|---|---|---|
| `essentials` | Platform Team | TDD, debugging, planning, git worktrees (14 skills) + feature-dev (3 agents) + PR review (6 agents) — best starting point | 96% |
| `appsec` | Platform Team | Catalog-driven security scanning: admin preference profiles (Fortify or GitLab SAST, GitLab dependency/secret/container scanning), CI/CD Catalog versions resolved every run, fix loop + triage plan — plus OWASP WSTG DAST sim. | 96% |
| `code-quality` | Platform Team | lint-and-validate + api-design-principles + openapi-spec-generation + doc-coauthoring | 97% |
| `superpowers` | Vendored (obra) | 14 skills: TDD, debugging, planning, worktrees, code review, brainstorming. **Already in essentials.** | 92% |
| `compound-engineering` | Vendored (EveryInc) | 38 skills + 50 specialised review agents: architecture, performance, security, data integrity… | 95% |
| `gstack` | Vendored (Garry Tan) | 54 skills: QA, browser automation, design consultation, production safety gates, context management | 88% |
| `ruflo` | Vendored (rUv) | 33 skills: AgentDB memory, SPARC methodology, swarm orchestration, GitHub automation | 62%² |
| `getshitdone` | Vendored (gsd-build) | 66 `/gsd` slash commands: Discuss→Plan→Execute→Verify lifecycle | 90% |
| `anthropic-dev-skills` | Vendored (Anthropic) | claude-api, mcp-builder, webapp-testing, dual-mode (4 skills) | 97% |
| `obsidian` | Vendored (Steph Ango) | obsidian-markdown, bases, CLI, json-canvas, defuddle (5 skills) | 96% |
| `anthropic-feature-dev` | Vendored (Anthropic) | 7-phase feature-dev: 3 agents + /feature-dev command. **Already in essentials.** | 98% |
| `anthropic-pr-review` | Vendored (Anthropic) | 6-agent parallel PR review + /review-pr command. **Already in essentials.** | 97% |
| `anthropic-hookify` | Vendored (Anthropic) | Git hooks framework + writing-rules skill + /hookify command | 87% |
| `frontend-design` | Vendored (Anthropic) | Frontend design patterns skill | 98% |
| `ponytail` | Vendored (Dietrich Gebert) | 6 skills: lazy-senior-dev mode, over-engineering review/audit, debt ledger + session hooks (needs `node`) | 92% |
| `agent-skills` | Vendored (Addy Osmani) | 24 production-engineering skills + 4 reviewer/auditor agents + skill-discovery session hook (needs `jq`) | 96% |
| `trailofbits-skills` | Vendored (Trail of Bits) | 33 security skills: audit workflows, Semgrep/CodeQL authoring, SARIF, supply-chain, fuzzing handbook | 97% |

> ¹ LLM-as-judge confidence (0–100%) that the plugin contains no malicious content, scanned 2026-07-05 per plugin against the CI scanner's five risk categories (prompt injection, data exfiltration, destructive commands, embedded secrets, scope creep) by Claude agents (Fable 5 for essentials/superpowers/obsidian/feature-dev/pr-review/frontend-design/ponytail/agent-skills/trailofbits-skills; Sonnet 4.6 for the rest). Higher = cleaner. Scores reflect risk indicators found, not overall quality; the CI LLM scanner independently gates every MR. Full findings are in PR history.
> ² ruflo's score reflects airgap/scope findings, not malice: 3 flow-nexus skills route to a commercial cloud service (forwards API keys, Stripe billing), ~13 skills require `npx <pkg>@latest` at runtime, and one skill file contains gstack content verbatim (vendoring contamination). Remediation tracked as a follow-up.

> All content is vendored at a fixed commit — no runtime network calls to upstream repos required by the marketplace itself. Individual skills that need network or local tools are flagged in `VENDORED.md` and the plugin descriptions. See `VENDORED.md` for commit SHAs and license notes.

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

**Everything else degrades gracefully — never a hard failure:** `jq` (severity
summary; see below), `curl` (only for live catalog; falls back to vendored
snapshots), `unzip`/`xmllint` (only for Fortify/Parasoft summaries), `glab`
(only for the optional end-of-run MR offer). `python3` is **not** required at
runtime.

### Step 1 — Mirror the analyzer images to your registry

Mirror these four images into your internal JFrog (their scan rules and
vulnerability DBs are baked in — **no network happens inside the containers**):

```
registry.gitlab.com/security-products/semgrep:6                 → <your-registry>/security/semgrep:6
registry.gitlab.com/security-products/secrets:7                 → <your-registry>/security/secrets:7
registry.gitlab.com/security-products/dependency-scanning:2     → <your-registry>/security/dependency-scanning:2
registry.gitlab.com/security-products/container-scanning:8      → <your-registry>/security/container-scanning:8
```

Then set each category's `image:` in the `company` profile to the mirrored path.
`image:` is what actually runs (admin-pinned); the `component:` path is resolved
each run only for its usage guide and a drift advisory that tells you when to
bump the pin.

### Step 2 — Point the profile at your GitLab and turn on airgap

```yaml
settings:
  airgap: true                 # internal endpoints only; refuses the public-test profile
  container_runtime: auto      # auto-detect docker or podman
  catalog:
    mode: online               # resolve customized components live against your GitLab
    auth_token_env: ""         # see Step 4
profiles:
  company:
    gitlab_instance: https://gitlab.your-company.internal
    categories:
      sast:
        component: components/sast/sast     # or your customized fork's path
        image: <your-registry>/security/semgrep:6
        runner: gitlab-sast.sh
        enabled: true
      # …dependency_scanning, secret_detection, container_scanning…
```

`airgap: true` also works alongside internet-connected sites — flip it to
`false` (or use the shipped `public-test` profile) when you *do* have internet,
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

The skill tries **anonymous** API reads against your GitLab first. If your
instance disables them, create a `read_api` Personal Access Token, put it in an
env var, and name that var in the config:

```yaml
settings:
  catalog:
    auth_token_env: GITLAB_READ_TOKEN     # the skill reads $GITLAB_READ_TOKEN
```

If neither works, the skill continues on the vendored snapshots in
`reference/catalog/` and tells the user exactly what to configure. Refresh those
snapshots periodically per `UPDATE-GUIDE.md` (Scenario 6).

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

---

## For teams: create your own private marketplace

Team skills live in your own private repo — **not** in this central catalog. This means:

- Plugin names and skill descriptions are never visible to other teams
- You control your own release cadence
- You can offer multiple granular plugins (e.g. one per domain) so developers install only what they need
- You never need Platform Team approval to add or update your own skills

### Step 1 — Create and structure your repo

Create a new project under the `skillshub` GitLab group named `<team-name>-skills`.

> **Set the project visibility to Private.** The `skillshub` group itself is public — private projects within it are hidden from non-members. Add your team members directly to the project to keep it invisible in the group listing.

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
  scanner-config.yaml       ← optional: tune scanner threshold/prompts
  .gitlab-ci.yml            ← required: include the skill scanner component
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
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner-component/skill-scanner-component@~latest
```

> **`LITELLM_API_KEY` required:** Add it as a masked CI/CD variable in your project's **Settings → CI/CD → Variables**. If you don't have one, raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

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
/plugin marketplace add https://gitlab.company.com/skillshub/<team-name>-skills.git
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

2. Create a new plugin directory and copy content:
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

4. If broadly useful for all developers, also add to `plugins/essentials/skills/`.

5. Register in `.claude-plugin/marketplace.json` — add an entry to the `plugins` array.

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
.gitlab-ci.yml                         CI: JSON validation + skill scanner across all plugins
CODEOWNERS                             Write-access rules with [Section][1] approval counts
VENDORED.md                            Upstream SHAs, license notes, update cadence
CLAUDE.md                              Project context for contributors

plugins/
  essentials/                          Curated starter pack (Platform Team maintained)
    .claude-plugin/plugin.json
    skills/   ← superpowers 14 skills
    agents/   ← feature-dev 3 agents + pr-review 6 agents
    commands/ ← feature-dev.md + review-pr.md
    hooks/    ← superpowers hooks
    assets/   ← superpowers assets

  superpowers/                         Vendored: obra/superpowers (14 skills)
  compound-engineering/                Vendored: EveryInc (38 skills + 50 agents)
  gstack/                              Vendored: garrytan/gstack (54 skills)
  ruflo/                               Vendored: ruvnet/ruflo (33 skills)
  getshitdone/                         Vendored: gsd-build (66 /gsd commands)
  anthropic-dev-skills/                Vendored: anthropics/skills (4 skills)
  obsidian/                            Vendored: kepano/obsidian-skills (5 skills)
  anthropic-feature-dev/               Vendored: anthropics/claude-plugins-official
  anthropic-pr-review/                 Vendored: anthropics/claude-plugins-official
  anthropic-hookify/                   Vendored: anthropics/claude-plugins-official
  frontend-design/                     Vendored: anthropics/skills (1 skill)
  ponytail/                            Vendored: DietrichGebert/ponytail (6 skills + mode hooks)
  agent-skills/                        Vendored: addyosmani/agent-skills (24 skills + 4 agents)
  trailofbits-skills/                  Vendored: trailofbits/skills (33 skills, curated subset)
  appsec/                              Platform Team — 2 security scanning skills
  code-quality/                        Platform Team — 4 code/doc quality skills

ci/
  skill-scanner/                       Scanner implementation (scanner.py, Dockerfile, config.yaml)
    scanner.py
    config.yaml                        Default prompts and threshold (editable without rebuild)
    Dockerfile
    requirements.txt
    scanner-config.example.yaml        Template for teams to copy into their repo

skill-scanner-component/              GitLab CI component (component spec + docs)
  templates/
    skill-scanner-component.yml        Component spec — inputs: stage, skills_dir, threshold,
                                       fail_on_review, scanner_model, image
    README.md                          Platform Team reference (publishing, calibration, local runs)
  .gitlab-ci.yml                       CI for validating and smoke-testing the component
  README.md                            Tenant reference (how to add the scanner to your skills repo)

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
| `plugins/<vendored-source>/` | Platform Team | 1 |
| `CODEOWNERS`, `VENDORED.md`, `ci/`, `.gitlab-ci.yml` | Platform Team | 1 |

Team skill content lives in separate private repos and is governed entirely by the team — no entry in this table covers it. The Platform Team has no read access to those repos unless explicitly added.

---

## Skill scanner — CI safety gate

Every team skills repo should include the scanner. It evaluates each `SKILL.md` using an LLM-as-judge and fails the pipeline if safety confidence is below threshold.

```yaml
# .gitlab-ci.yml in your skills repo — this is the complete config
include:
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner-component/skill-scanner-component@~latest
```

Set `LITELLM_API_KEY` as a masked CI/CD variable. That's it.

Results appear as named test cases in the MR Tests tab. Full docs: `ci/skill-scanner/README.md`.

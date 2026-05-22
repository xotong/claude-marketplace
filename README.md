# Claude Code Marketplace

Central plugin marketplace. One URL to configure; all team and platform skills flow from here.

| Plugin | What it gives you |
|---|---|
| **essentials** | Start here — TDD, debugging, planning, feature dev, PR review in one install. |
| **appsec** | Security scanning: Fortify, Parasoft, Scantist, Trivy (CI-mirror) + OWASP WSTG DAST sim. |
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
| **`<team-name>`** | Your team's private skills, hosted in a separate repo. |

---

## For tenants: one-time Claude Code setup

### Step 1 — Add the marketplace

In any Claude Code session, run:

```
/plugin marketplace add https://gitlab.company.com/skillshub/claude-marketplace.git
```

Claude Code will clone the catalog and register it as `platform-claude-marketplace`. You only need to do this once per machine.

> **Git auth prerequisite:** Claude Code clones the marketplace using your system git.
> You need git configured to authenticate to internal GitLab before running the command above.
>
> **macOS**
> ```bash
> # Option A — SSH key (recommended)
> ssh-keygen -t ed25519 -C "your@email.com"
> # Add ~/.ssh/id_ed25519.pub to your GitLab profile → SSH Keys
>
> # Option B — Personal Access Token via credential helper
> git config --global credential.helper osxkeychain
> # Then `git clone` any internal repo; macOS will prompt for username/PAT and save it
> ```
>
> **Ubuntu / Debian**
> ```bash
> # Option A — SSH key
> ssh-keygen -t ed25519 -C "your@email.com"
> # Add ~/.ssh/id_ed25519.pub to your GitLab profile → SSH Keys
>
> # Option B — Personal Access Token via credential store
> git config --global credential.helper store
> git clone https://gitlab.company.com/skillshub/claude-marketplace.git /tmp/test-clone
> # Enter your GitLab username and PAT when prompted; credentials are saved to ~/.git-credentials
> rm -rf /tmp/test-clone
> ```
>
> **WSL (Windows Subsystem for Linux)**
> ```bash
> # Recommended: delegate to the Windows Git credential manager
> git config --global credential.helper "/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe"
> # Then authenticate once via the Windows Git Credential Manager dialog
> ```
>
> Verify with: `git ls-remote https://gitlab.company.com/skillshub/claude-marketplace.git`
> If that prints refs without prompting, you're set.

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

**Your team's skills:**
```
/plugin install my-team@platform-claude-marketplace
/reload-plugins
```

Replace `my-team` with your team's plugin name (same as the `name` in your team's `plugin.json`). Your team repo must be listed in the catalog — see "For teams" below.

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

If a plugin is missing after install, check that your git credentials can reach the marketplace repo and re-run the install command.

> **Need a `LITELLM_API_KEY`?** This key is needed if your team runs the skill scanner CI job. If you don't have one, raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

---

## Plugin catalog

| Plugin | Type | What's inside |
|---|---|---|
| `essentials` | Platform Team | TDD, debugging, planning, git worktrees (14 skills) + feature-dev (3 agents) + PR review (6 agents) — best starting point |
| `appsec` | Platform Team | appsec-scan (Fortify/Parasoft/Scantist/Trivy CI-mirror) + appsec-dast-sim (OWASP WSTG v4.2) |
| `code-quality` | Platform Team | lint-and-validate + api-design-principles + openapi-spec-generation + doc-coauthoring |
| `superpowers` | Vendored (obra) | 14 skills: TDD, debugging, planning, worktrees, code review, brainstorming. **Already in essentials.** |
| `compound-engineering` | Vendored (EveryInc) | 38 skills + 50 specialised review agents: architecture, performance, security, data integrity… |
| `gstack` | Vendored (Garry Tan) | 54 skills: QA, browser automation, design consultation, production safety gates, context management |
| `ruflo` | Vendored (rUv) | 33 skills: AgentDB memory, SPARC methodology, swarm orchestration, GitHub automation |
| `getshitdone` | Vendored (gsd-build) | 66 `/gsd` slash commands: Discuss→Plan→Execute→Verify lifecycle |
| `anthropic-dev-skills` | Vendored (Anthropic) | claude-api, mcp-builder, webapp-testing, dual-mode (4 skills) |
| `obsidian` | Vendored (Steph Ango) | obsidian-markdown, bases, CLI, json-canvas, defuddle (5 skills) |
| `anthropic-feature-dev` | Vendored (Anthropic) | 7-phase feature-dev: 3 agents + /feature-dev command. **Already in essentials.** |
| `anthropic-pr-review` | Vendored (Anthropic) | 6-agent parallel PR review + /review-pr command. **Already in essentials.** |
| `anthropic-hookify` | Vendored (Anthropic) | Git hooks framework + writing-rules skill + /hookify command |
| `frontend-design` | Vendored (Anthropic) | Frontend design patterns skill |

> All content is vendored at a fixed commit — no runtime network calls to upstream repos. Fully offline once the marketplace is cloned. See `VENDORED.md` for commit SHAs and license notes.

---

## For teams: create and publish your skills repo

### Step 1 — Create and structure your repo

Create a new project under the `skillshub` GitLab group named `<team-name>-skills`.

> **Set the project visibility to Private.** This ensures only your team members (and the Platform Team) can read the skill content. The `skillshub` group itself is public — private projects within it are still fully hidden from non-members. Add your team members directly to the project (not to the group) to keep the project invisible even in the group listing.

Structure it as follows:

```
<team-name>-skills/
  .claude-plugin/
    plugin.json             ← required
  skills/
    <skill-name>/
      SKILL.md              ← required
      supporting-doc.md     ← optional
  scanner-config.yaml       ← optional: tune scanner threshold/prompts
  .gitlab-ci.yml            ← required: include the skill scanner component
```

**`plugin.json` minimum:**
```json
{
  "name": "<team-name>",
  "version": "0.1.0",
  "description": "Skills for the <team-name> team.",
  "author": { "name": "<Team Name>" }
}
```

**`.gitlab-ci.yml` minimum:**
```yaml
include:
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner@~latest
```

> **`LITELLM_API_KEY` required:** Add it as a masked CI/CD variable in your project's **Settings → CI/CD → Variables**. If you don't have one, raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

### Step 2 — Write a skill

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

### Step 3 — List in the marketplace

Open an MR against this repo using the **"Add Team to Marketplace"** MR template.
The Platform Team reviews structure, not skill content — you own quality within your repo.

---

## For contributors: adding and updating plugins

Each upstream source has its own plugin directory under `plugins/<source-name>/`. `plugins/platform-verified/` is a consolidated reference copy used by the CI scanner — it is not listed in the marketplace catalog.

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

4. Also copy the skills into `plugins/platform-verified/` (CI scanner reference):
   ```bash
   cp -r /tmp/<source-name>/skills/. plugins/platform-verified/skills/
   ```

5. If broadly useful for all developers, also add to `plugins/essentials/skills/`.

6. Register in `.claude-plugin/marketplace.json` — add an entry to the `plugins` array.

7. Record provenance in `VENDORED.md` (upstream URL, commit SHA, date, license).

8. Open an MR using the **"Add Skill to Platform-Verified"** MR template. Platform Team is a required approver.

### Updating an existing upstream source

1. Clone the upstream at the new commit:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   ```

2. Replace the content in the plugin directory:
   ```bash
   rm -rf plugins/<source-name>/skills/*
   cp -r /tmp/<source-name>/skills/. plugins/<source-name>/skills/
   # Also update platform-verified and essentials if they include this source
   ```

3. Update the SHA and date in `VENDORED.md`.

4. Bump `version` in `plugins/<source-name>/.claude-plugin/plugin.json` and open an MR.

Platform Team is a required approver (CODEOWNERS).

---

## Repo layout

```
.claude-plugin/marketplace.json        Central catalog — Platform Team only
.gitlab-ci.yml                         CI: JSON validation + scanner on platform-verified (changed files only)
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

  platform-verified/                   Consolidated reference copy (CI scanner, not in marketplace catalog)
    .claude-plugin/plugin.json
    skills/   ← 155 skills from all 11 sources
    agents/   ← 58 agents
    commands/ ← 72 commands (including 66 /gsd commands)
    hooks/    ← superpowers + hookify hooks
    matchers/ ← hookify matchers
    utils/    ← hookify utils
    core/     ← hookify core
    assets/   ← superpowers assets
    references/ ← getshitdone reference docs

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
  appsec/                              Platform Team — 2 security scanning skills
  code-quality/                        Platform Team — 4 code/doc quality skills

ci/
  skill-scanner/                       LLM-as-judge safety scanner + GitLab CI component
    scanner.py
    config.yaml                        Default prompts and threshold (editable without rebuild)
    Dockerfile
    gitlab-component.yml
    README.md

.gitlab/
  merge_request_templates/
    add-team-to-marketplace.md
    add-skill-to-platform-verified.md
```

---

## Governance

| Path | Who can merge | Minimum approvals |
|---|---|---|
| `.claude-plugin/marketplace.json` | Platform Team | 1 |
| `plugins/essentials/` | Platform Team | 1 |
| `plugins/platform-verified/` | Platform Team | 1 |
| `plugins/appsec/` | Platform Team | 1 |
| `plugins/code-quality/` | Platform Team | 1 |
| `plugins/<vendored-source>/` | Platform Team | 1 |
| `CODEOWNERS`, `VENDORED.md`, `ci/`, `.gitlab-ci.yml` | Platform Team | 1 |

Team skill content lives in separate private repos. The Platform Team has no read access to those repos unless explicitly added.

---

## Skill scanner — CI safety gate

Every team skills repo should include the scanner. It evaluates each `SKILL.md` using an LLM-as-judge and fails the pipeline if safety confidence is below threshold.

```yaml
# .gitlab-ci.yml in your skills repo — this is the complete config
include:
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner@~latest
```

Set `LITELLM_API_KEY` as a masked CI/CD variable. That's it.

Results appear as named test cases in the MR Tests tab. Full docs: `ci/skill-scanner/README.md`.

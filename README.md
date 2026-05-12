# Claude Code Marketplace

Central plugin marketplace. One URL to configure; all team and platform skills flow from here.

| Category | What it means |
|---|---|
| **platform-verified** | Skills curated and approved by the Platform Team. Safe on any machine. |
| **vendored** | Upstream community skills pinned at a specific commit. Audited before inclusion. |
| **team** | Team-specific skills in private repos. Listed in the catalog; content stays private. |

---

## For tenants: one-time Claude Code setup

Add to `~/.claude/settings.json` (create if it doesn't exist):

```json
{
  "extraKnownMarketplaces": {
    "claude-marketplace": {
      "source": {
        "source": "git",
        "url": "https://gitlab.company.com/skillshub/claude-marketplace.git"
      }
    }
  }
}
```

> **Git auth prerequisite:** Claude Code clones marketplace repos using your system git.
> You need git configured to authenticate to internal GitLab — either an SSH key registered
> in your GitLab profile, or a Personal Access Token stored in your macOS Keychain.
> If `git clone https://gitlab.company.com/any-repo.git` works in your terminal, you're set.

### Recommended install (everyone)

```
/plugin install platform-verified@claude-marketplace
/reload-plugins
```

Gives you: platform coding conventions, internal docs navigation, and LiteLLM API guidance.

### Popular vendored plugins

```
/plugin install superpowers@claude-marketplace          # TDD, debugging, planning, git worktrees
/plugin install anthropic-feature-dev@claude-marketplace  # 7-phase feature dev workflow
/plugin install anthropic-pr-review@claude-marketplace    # 6-agent parallel PR review
/plugin install compound-engineering@claude-marketplace   # 22-agent code review + knowledge loop
/plugin install anthropic-dev-skills@claude-marketplace   # Claude API, Playwright, MCP building
/plugin install anthropic-hookify@claude-marketplace      # Configure hooks via Markdown rules
/plugin install frontend-design@claude-marketplace        # Production-grade UI design
/plugin install obsidian@claude-marketplace               # Obsidian vault Markdown, Bases, Canvas
/plugin install gstack@claude-marketplace                 # Virtual team: CEO/EM/Designer/QA roles
/plugin install getshitdone@claude-marketplace            # Context-rot prevention, /gsd workflow
/plugin install ruflo@claude-marketplace                  # Multi-agent swarm + persistent memory
```

### Your team's skills

```
/plugin install <team-name>@claude-marketplace
/reload-plugins
```

> Your team repo must exist in the `skillshub` GitLab group and be listed in the catalog.
> See "For teams" below if it isn't yet.

---

## Plugin catalog

| Plugin | Version | Description |
|---|---|---|
| `platform-verified` | 0.1.0 | platform conventions, internal docs, LiteLLM API |
| `superpowers` | 5.1.0 | TDD, debugging, planning, code review, git worktrees |
| `anthropic-feature-dev` | 1.0.0 | 7-phase feature development with 3 specialist agents |
| `anthropic-pr-review` | 1.0.0 | 6-agent parallel PR review with confidence scoring |
| `compound-engineering` | 3.7.0 | 22-agent code review, compound knowledge loop, planning |
| `anthropic-dev-skills` | 0.1.0 | Claude API, Playwright testing, MCP server building |
| `anthropic-hookify` | 1.0.0 | Markdown-configured session hooks |
| `frontend-design` | 0.1.0 | Distinctive, production-grade frontend interfaces |
| `obsidian` | 1.0.1 | Obsidian vault Markdown, Bases, Canvas, CLI and web extraction |
| `gstack` | 1.0.0 | Virtual engineering team — CEO/EM/Designer/QA roles, browser QA, production gates |
| `getshitdone` | 1.40.0 | Context-rot prevention — Discuss→Plan→Execute→Verify loop, 66 /gsd commands |
| `ruflo` | 2.5.0 | Multi-agent swarm, AgentDB persistent memory, SPARC methodology (38 skills) |

---

## For teams: create and publish your skills repo

### Step 1 — Request a repo

Open an issue titled `[New team repo] <team-name>-skills` in this repo. Include:
- Team name and GitLab group path for access control
- Slack channel
- Brief description of planned skills

The Platform Team creates `skillshub/<team-name>-skills` with access restricted to your team.
No one outside your team will have read access.

### Step 2 — Structure your repo

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

Plus set `LITELLM_API_KEY` as a masked CI/CD variable in your project settings.

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

### Step 4 — List in the marketplace

Open an MR against this repo using the **"Add Team to Marketplace"** MR template.
The Platform Team reviews structure, not skill content — you own quality within your repo.

---

## For contributors: platform-verified skills

`plugins/platform-verified/` is for cross-team skills reviewed and endorsed by the Platform Team.

**Criteria:** useful to ≥ 3 teams · no team-specific internal references · no destructive commands without confirmation · no external API calls · passes CI scanner at threshold 0.90.

Use the **"Add Skill to Platform-Verified"** MR template. Platform Team is a required approver (CODEOWNERS).

---

## Repo layout

```
.claude-plugin/marketplace.json        Central catalog — Platform Team only
.gitlab-ci.yml                         CI: JSON validation + scanner on platform-verified
CODEOWNERS                             Write-access rules with [Section][1] approval counts
VENDORED.md                            Upstream SHAs, license notes, update cadence

plugins/
  platform-verified/                   Official platform skills (CODEOWNERS protected)
    .claude-plugin/plugin.json
    skills/
      platform-conventions/SKILL.md     Commit style, code style, PR conventions
      internal-docs-navigator/SKILL.md Confluence/GitLab navigation guidance
      litellm-api/SKILL.md             Internal LiteLLM gateway usage

  superpowers/                         Vendored: obra/superpowers v5.1.0 (MIT)
  frontend-design/                     Vendored: anthropics/skills (see LICENSE.txt)
  anthropic-dev-skills/                Vendored: anthropics/skills — claude-api, playwright, mcp
  anthropic-feature-dev/              Vendored: anthropics/claude-plugins-official (MIT)
  anthropic-pr-review/                 Vendored: anthropics/claude-plugins-official (MIT)
  anthropic-hookify/                   Vendored: anthropics/claude-plugins-official (MIT)
  compound-engineering/                Vendored: EveryInc/compound-engineering-plugin (MIT)
  obsidian/                            Vendored: kepano/obsidian-skills v1.0.1 (MIT)
  gstack/                              Vendored: garrytan/gstack (MIT)
  getshitdone/                         Vendored: gsd-build/get-shit-done v1.40.0 (MIT)
  ruflo/                               Vendored: ruvnet/ruflo v2.5.0 (MIT) — skills only

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
| `plugins/platform-verified/` | Platform Team | 1 |
| `plugins/<vendored>/` | Platform Team | 1 |
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

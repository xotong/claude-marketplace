# Claude Code Marketplace

Central plugin marketplace. One URL to configure; all team and platform skills flow from here.

| Plugin | What it gives you |
|---|---|
| **essentials** | Curated starter pack — install this first. TDD, debugging, planning, feature dev, PR review. |
| **platform-verified** | The full catalog — every vendored skill, agent, and command in one install. |
| **`<team-name>`** | Your team's private skills, hosted in a separate repo. |

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

### Start here (recommended for everyone)

```
/plugin install essentials@claude-marketplace
/reload-plugins
```

Gives you: TDD, systematic debugging, planning, git worktrees, 7-phase feature development, and 6-agent parallel PR review. A solid foundation for any developer.

### Want everything?

```
/plugin install platform-verified@claude-marketplace
/reload-plugins
```

Installs the full catalog: 149 skills, 58 agents, and 72 commands from 11 vendored sources.

### Your team's skills

```
/plugin install <team-name>@claude-marketplace
/reload-plugins
```

> Your team repo must exist in the `skillshub` GitLab group and be listed in the catalog.
> See "For teams" below if it isn't yet.

---

## Plugin catalog

| Plugin | Version | What's inside |
|---|---|---|
| `essentials` | 1.0.0 | **Starter pack:** superpowers (TDD, debugging, planning, git worktrees, 14 skills) + anthropic-feature-dev (3 agents, feature-dev command) + anthropic-pr-review (6 agents, review-pr command) |
| `platform-verified` | 1.0.0 | **Full catalog:** all 11 vendored sources — see breakdown below |

### What's in `platform-verified`

| Source | Skills / Agents / Commands |
|---|---|
| superpowers (obra) | 14 skills: TDD, debugging, planning, worktrees, code review, brainstorming… |
| gstack (Garry Tan) | 48 skills: CEO/EM/Designer/QA roles, browser QA, freeze, make-pdf… |
| compound-engineering (EveryInc) | 39 skills + 49 agents: parallel code review, knowledge loop… |
| getshitdone | 66 /gsd commands: Discuss→Plan→Execute→Verify lifecycle |
| ruflo (rUv) | 38 skills: AgentDB memory, SPARC, swarm, GitHub automation… |
| anthropic-feature-dev | 3 agents + feature-dev command |
| anthropic-pr-review | 6 agents + review-pr command |
| anthropic-hookify | writing-rules skill + hook automation agents/commands |
| anthropic-dev-skills | claude-api, webapp-testing, mcp-builder skills |
| frontend-design | frontend-design skill |
| obsidian (Steph Ango) | 5 skills: obsidian-markdown, bases, CLI, json-canvas, defuddle |

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

## For contributors: adding skills to platform-verified

`plugins/platform-verified/` is the full vendored catalog. To add a new upstream skill source:

1. Vendor the files into the relevant subdirectory (see VENDORED.md for pattern)
2. Merge skills into `plugins/platform-verified/skills/`, agents into `agents/`, commands into `commands/`
3. If the source is broadly useful, also add its core skills to `plugins/essentials/`
4. Open an MR using the **"Add Skill to Platform-Verified"** MR template
5. Update VENDORED.md provenance table and `marketplace.json` versions

Platform Team is a required approver (CODEOWNERS).

---

## Repo layout

```
.claude-plugin/marketplace.json        Central catalog — Platform Team only
.gitlab-ci.yml                         CI: JSON validation + scanner on platform-verified
CODEOWNERS                             Write-access rules with [Section][1] approval counts
VENDORED.md                            Upstream SHAs, license notes, update cadence

plugins/
  essentials/                          Curated starter pack (Platform Team maintained)
    .claude-plugin/plugin.json
    skills/   ← superpowers 14 skills
    agents/   ← feature-dev 3 agents + pr-review 6 agents
    commands/ ← feature-dev.md + review-pr.md
    hooks/    ← superpowers hooks
    assets/   ← superpowers assets

  platform-verified/                   Full vendored catalog (CODEOWNERS protected)
    .claude-plugin/plugin.json
    skills/   ← 149 skills from all 11 sources
    agents/   ← 58 agents
    commands/ ← 72 commands (including 66 /gsd commands)
    hooks/    ← superpowers + hookify hooks
    matchers/ ← hookify matchers
    utils/    ← hookify utils
    core/     ← hookify core
    assets/   ← superpowers assets
    references/ ← getshitdone reference docs

  hello-xotong1/                       Smoke-test plugin

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

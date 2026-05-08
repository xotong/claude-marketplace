# xotong1 Skills Hub — Claude Code Marketplace

Central plugin marketplace for xotong1. One URL to configure; all team and platform skills flow through here.

- **Platform-verified** skills: curated by the Platform Team, safe to install on any machine.
- **Team skills**: each team maintains a private repo inside the `skillshub` GitLab group; the catalog here lists them so tenants can discover and install them.
- **Vendored upstream**: well-known community skills (superpowers, frontend-design) pinned and audited by the Platform Team.

---

## For tenants: one-time Claude Code setup

Add one entry to your `~/.claude/settings.json`. If the file does not exist, create it.

```json
{
  "extraKnownMarketplaces": {
    "xotong1-marketplace": {
      "source": {
        "source": "git",
        "url": "https://gitlab.company.com/skillshub/claude-marketplace.git"
      }
    }
  }
}
```

Replace `gitlab.company.com` with your internal GitLab hostname.

> **Git authentication prerequisite**: Claude Code clones marketplace repos using your system git. You must have git configured to authenticate to the internal GitLab — either an SSH key registered in your GitLab profile, or a Personal Access Token stored in your macOS Keychain. If you can run `git clone https://gitlab.company.com/any-repo.git` in your terminal today, you are already set.

### Install platform-verified skills (recommended for everyone)

```
/plugin install platform-verified@xotong1-marketplace
/reload-plugins
```

### Install your team's skills

```
/plugin install <your-team-name>@xotong1-marketplace
/reload-plugins
```

> Your team repo must already exist in the `skillshub` GitLab group and be listed in `.claude-plugin/marketplace.json`. See the section below if it is not yet listed.

### Install community skills (vendored)

```
/plugin install superpowers@xotong1-marketplace
/plugin install frontend-design@xotong1-marketplace
/reload-plugins
```

---

## For teams: create and publish your skills repo

### Step 1 — Request a repo in the skillshub group

Open an issue in this repo using the title: `[New team repo] <team-name>-skills`. Include:

- Team name and GitLab group/subgroup path for access control
- Slack channel or contact for the Platform Team to reach you
- Brief description of what kinds of skills you plan to build

The Platform Team will create `skillshub/<team-name>-skills` and grant your team Developer+ access. No one outside your team will have read access to that repo.

### Step 2 — Structure your repo

Your repo must follow this layout for Claude Code to recognise it as a plugin:

```
<team-name>-skills/
  .claude-plugin/
    plugin.json             ← required: plugin manifest
  skills/
    <skill-name>/
      SKILL.md              ← required: the skill itself
      supporting-doc.md     ← optional: referenced by SKILL.md
```

**Minimal `plugin.json`:**

```json
{
  "name": "<team-name>",
  "version": "0.1.0",
  "description": "Skills for the <team-name> team.",
  "author": {
    "name": "<Team Name>"
  }
}
```

Bump `version` each time you publish a change that tenants should pull. Use [semver](https://semver.org): `0.1.0` → `0.1.1` for fixes, `0.2.0` for new skills, `1.0.0` for breaking changes.

### Step 3 — Write your skills

A skill is a markdown file with a YAML frontmatter block followed by the instruction body.

**`skills/<skill-name>/SKILL.md` template:**

```markdown
---
name: <skill-name>
description: >
  One to three sentences. Start with what this skill does. Then list the
  trigger phrases or situations where Claude should activate it. Be specific —
  Claude matches this description against user messages to decide whether to
  load the skill. Vague descriptions cause false positives and missed triggers.
---

# <Skill Name>

(Write the instructions Claude should follow when this skill is active.
Be explicit. Claude reads this as a system-level instruction set.)

## What to do

1. Step one.
2. Step two.

## What NOT to do

- Do not call external APIs unless the user has explicitly authorised it.
- Do not write or delete files outside the project directory.
```

**Description field tips:**

- Include example trigger phrases: `"Use this skill when the user says 'deploy to staging', 'run the release pipeline', or asks to promote a build."`
- Include anti-triggers if there is ambiguity: `"Do NOT activate for local test runs or unit tests."`
- Keep it under 200 words; Claude truncates long descriptions.

**Skill dos and don'ts:**

| Do | Don't |
|---|---|
| Give Claude explicit step-by-step instructions | Leave behaviour undefined and hope Claude infers it |
| Reference supporting docs with relative paths (`./runbook.md`) | Embed full runbook content inline if it is > 300 lines |
| State clearly what tools Claude may and may not use | Assume Claude knows your team's conventions |
| Version-pin any external tool or API the skill references | Reference `latest` or leave versions implicit |
| Include an example of a correct output in the skill body | Skip examples and then wonder why output is inconsistent |

### Step 4 — Request to be listed in the marketplace

Once your repo has at least one working skill, open a Merge Request against **this repo** (`skillshub/claude-marketplace`) that adds an entry to `.claude-plugin/marketplace.json` under `plugins[]`.

**Entry format:**

```json
{
  "name": "<team-name>",
  "source": {
    "source": "git",
    "url": "https://gitlab.company.com/skillshub/<team-name>-skills.git"
  },
  "version": "<version from your plugin.json>",
  "description": "One line describing what this team's skills cover.",
  "author": {
    "name": "<Team Name>"
  },
  "category": "team",
  "keywords": ["<team-name>", "team"]
}
```

The Platform Team will review that your repo is correctly structured and that the listed version exists, then merge. **The Platform Team will not audit skill content** — your team owns the quality and safety of your own skills.

---

## For contributors: adding a skill to platform-verified

`plugins/platform-verified/` is for skills that are useful across all teams and have been reviewed by the Platform Team. These are safe to install on any machine.

**Criteria for platform-verified:**

- Applicable to at least three different teams (not team-specific workflow)
- No references to internal systems that only some teams can access
- No shell commands that modify files outside the project scope
- No instructions to call external URLs or third-party APIs
- Passes the CI skill safety scan (see `ci/` directory)

**Contribution process:**

1. Fork or branch from `main` in this repo.
2. Create `plugins/platform-verified/skills/<skill-name>/SKILL.md` following the template above.
3. Open a Merge Request. Title: `[platform-verified] Add <skill-name> skill`.
4. The Platform Team is a required approver (enforced by CODEOWNERS). Expect review within 3 business days.
5. Do not modify `marketplace.json` — the Platform Team handles version bumps for `platform-verified` as a bundle.

---

## Repo layout

```
.claude-plugin/
  marketplace.json          Central plugin catalog — platform team only
CODEOWNERS                  Write-access rules — platform team only
VENDORED.md                 Upstream provenance for vendored plugins

plugins/
  platform-verified/        Platform-curated skills (CODEOWNERS protected)
    .claude-plugin/
      plugin.json
    skills/
      <skill-name>/
        SKILL.md

  superpowers/              Vendored: obra/superpowers (MIT)
  frontend-design/          Vendored: anthropics/skills (see LICENSE.txt)
  hello-xotong1/            Smoke-test plugin

ci/
  skill-scanner/            Skill safety CI scanner (LLM-as-judge via LiteLLM)
```

---

## Governance summary

| Path | Who can merge |
|---|---|
| `.claude-plugin/marketplace.json` | Platform Team only |
| `plugins/platform-verified/` | Platform Team only |
| `plugins/<vendored>/` | Platform Team only |
| `CODEOWNERS`, `VENDORED.md` | Platform Team only |
| Everything else (docs, ci tooling) | Platform Team only (default) |

Team skill content lives in separate private repos. The Platform Team never has read access to those repos unless explicitly added.

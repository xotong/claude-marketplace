# Claude Code Marketplace

Central plugin marketplace. One URL to configure; all team and platform skills flow from here.

| Plugin | What it gives you |
|---|---|
| **essentials** | Curated starter pack — install this first. TDD, debugging, planning, feature dev, PR review. |
| **platform-verified** | The full catalog — every vendored skill, agent, and command in one install. |
| **`<team-name>`** | Your team's private skills, hosted in a separate repo. |

---

## For tenants: one-time Claude Code setup

### Step 1 — Add the marketplace

In any Claude Code session, run:

```
/plugin marketplace add https://gitlab.company.com/skillshub/claude-marketplace.git
```

Claude Code will clone the catalog and register it as `claude-marketplace`. You only need to do this once per machine.

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
/plugin install essentials@claude-marketplace
/reload-plugins
```

Gives you: TDD, systematic debugging, planning, git worktrees, 7-phase feature development, and 6-agent parallel PR review.

**Want everything?**
```
/plugin install platform-verified@claude-marketplace
/reload-plugins
```

Installs the full catalog: 149 skills, 58 agents, and 72 commands from 11 vendored sources.

**Your team's skills:**
```
/plugin install my-team@claude-marketplace
/reload-plugins
```

Replace `my-team` with your team's plugin name (same as the `name` in your team's `plugin.json`). Your team repo must be listed in the catalog — see "For teams" below.

### Step 3 — Verify your install

After `/reload-plugins`, run:
```
/plugins
```

This lists all installed plugins and their loaded skills. Confirm `essentials` (or `platform-verified`) appears and the skill count matches what you expect. If a plugin is missing, check that your git credentials can reach the marketplace repo and re-run the install command.

> **Need a `LITELLM_API_KEY`?** This key is needed if your team runs the skill scanner CI job. If you don't have one, raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

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

> All sources are vendored at a fixed commit — no runtime network calls to upstream repos. Works fully offline once the marketplace is cloned. See VENDORED.md for commit SHAs and license notes.

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

## For contributors: adding skills to platform-verified

`plugins/platform-verified/` and `plugins/essentials/` are the two user-facing plugins. All vendored content lives inside them. Here is the explicit workflow to add or update an upstream skill source:

### Adding a new upstream source

1. Clone the upstream repo into a temp directory:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   ```

2. Copy the relevant skill files into `plugins/platform-verified/`:
   ```bash
   # Skills go into skills/
   cp -r /tmp/<source-name>/skills/. plugins/platform-verified/skills/

   # Agents (if any) go into agents/
   cp -r /tmp/<source-name>/agents/. plugins/platform-verified/agents/

   # Commands (if any) go into commands/
   cp -r /tmp/<source-name>/commands/. plugins/platform-verified/commands/
   ```

3. If the source is broadly useful (good for most developers), also copy its core skills into `plugins/essentials/`:
   ```bash
   cp -r /tmp/<source-name>/skills/. plugins/essentials/skills/
   ```

4. Record the provenance in `VENDORED.md`:
   - Add a row to the provenance table with the upstream URL, commit SHA (`git -C /tmp/<source-name> rev-parse HEAD`), date, and license
   - Add a `### <source-name>` section describing what was included/excluded

5. Bump `version` in `plugins/platform-verified/.claude-plugin/plugin.json` and `plugins/essentials/.claude-plugin/plugin.json` (if changed).

6. Open an MR using the **"Add Skill to Platform-Verified"** MR template. Platform Team is a required approver.

### Updating an existing upstream source

1. Clone the upstream at the new commit:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   ```

2. Identify which skill directories belong to this source (check VENDORED.md for the list).

3. Remove the old files and copy the new ones:
   ```bash
   # Example: updating superpowers skills
   rm -rf plugins/platform-verified/skills/tdd \
          plugins/platform-verified/skills/debugging \
          plugins/platform-verified/skills/planning  # ... all superpowers skills
   cp -r /tmp/<source-name>/skills/. plugins/platform-verified/skills/

   # Repeat for essentials if the source appears there too
   ```

4. Update the SHA and date in `VENDORED.md`.

5. Bump versions and open an MR.

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

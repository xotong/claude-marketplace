## Add Vendored Plugin

**Use this template when:** You want to add or update an upstream open-source skills package as an installable plugin in the Platform Team catalog.

> **Criteria for inclusion (all must be true):**
> - Useful to at least three different teams (not a team-specific workflow)
> - No references to internal systems only some teams can access
> - No shell commands with irreversible effects without explicit user confirmation
> - No instructions to call external URLs or third-party APIs at runtime
> - Passes the CI skill safety scanner at threshold 0.90
> - License is compatible with internal distribution (MIT, Apache 2.0, BSD — check `VENDORED.md`)

---

### Plugin summary

- **Plugin name:** `<plugin-name>` (will be installable as `<plugin-name>@platform-claude-marketplace`)
- **Upstream URL:** `<upstream-repo-url>`
- **Upstream commit SHA:** `<sha>`
- **License:**
- **Which teams would benefit:** (name at least 3)
- **What problem does this solve:**

### Checklist (author)

**Repo structure:**
- [ ] Created `plugins/<plugin-name>/` directory
- [ ] Created `plugins/<plugin-name>/.claude-plugin/plugin.json` with `name`, `version`, `description`, `author`, `keywords`
- [ ] Description in `plugin.json` starts with `[Vendored: <upstream-url>]`
- [ ] All skill content is under `plugins/<plugin-name>/skills/` (agents under `agents/`, commands under `commands/`)
- [ ] Added an entry to `.claude-plugin/marketplace.json`

**Skill quality:**
- [ ] Each `SKILL.md` has correct YAML frontmatter with `name:` and `description:` fields
- [ ] Description fields include specific trigger phrases
- [ ] No hardcoded internal URLs, API keys, or system paths introduced
- [ ] No instructions added to call external services at runtime (airgap requirement)
- [ ] Tested locally: installed the plugin and verified at least one skill triggers correctly

**Provenance:**
- [ ] Added entry to `VENDORED.md`: upstream URL, commit SHA, date vendored, license, what was included/excluded

### Trigger phrases tested

List the exact phrases you tested that correctly activate a representative skill:
1.
2.
3.

---

### Checklist (Platform Team reviewer)

- [ ] CI skill scanner passed (threshold 0.90)
- [ ] License is compatible with internal distribution
- [ ] Plugin is genuinely cross-team
- [ ] No PII, credentials, or internal infrastructure details
- [ ] `VENDORED.md` entry is complete and accurate
- [ ] `marketplace.json` entry is correctly structured

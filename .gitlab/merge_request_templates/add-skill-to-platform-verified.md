## Add Skill to platform-verified

**Use this template when:** You want to contribute a skill to `plugins/platform-verified/` — skills that are useful across all teams and officially endorsed by the Platform Team.

> **Platform-verified criteria (all must be true):**
> - Useful to at least three different teams (not a team-specific workflow)
> - No references to internal systems only some teams can access
> - No shell commands with irreversible effects without explicit user confirmation
> - No instructions to call external URLs or third-party APIs
> - Passes the CI skill safety scanner at threshold 0.90

---

### Skill summary

- **Skill name:** `<skill-name>`
- **File path:** `plugins/platform-verified/skills/<skill-name>/SKILL.md`
- **Which teams would benefit:** (name at least 3)
- **What problem does this solve:**

### Checklist (author)

- [ ] `SKILL.md` has correct YAML frontmatter with `name:` and `description:` fields
- [ ] Description field includes specific trigger phrases (e.g. "Use when the user says '...'")
- [ ] Description field includes anti-triggers if there is potential for ambiguity
- [ ] Skill body gives Claude explicit step-by-step instructions — no vague guidance
- [ ] Skill body has a "What NOT to do" section or equivalent constraints
- [ ] No hardcoded internal URLs, API keys, or system paths
- [ ] No instructions to call external services
- [ ] Tested locally: installed the skill and verified it triggers correctly
- [ ] Tested locally: verified it does NOT trigger on unrelated prompts

### Trigger phrases tested

List the exact phrases you tested that correctly activate the skill:
1.
2.
3.

List any phrases you tested that correctly did NOT activate it:
1.
2.

---

### Checklist (Platform Team reviewer)

- [ ] CI skill scanner passed (threshold 0.90, fail_on_review: true)
- [ ] Skill is genuinely cross-team — not a wrapper for one team's internal tooling
- [ ] No PII, credentials, or internal infrastructure details in the skill body
- [ ] Trigger description is precise enough to avoid false positives
- [ ] `plugins/platform-verified/.claude-plugin/plugin.json` version bumped after merge

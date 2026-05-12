## Add Team to Marketplace

**Use this template when:** Your team's skills repo is ready and you want it listed in the marketplace catalog so tenants can discover and install it.

---

### Checklist (author)

- [ ] Team repo exists at `https://gitlab.company.com/skillshub/<team-name>-skills`
- [ ] Repo has `.claude-plugin/plugin.json` with `name`, `version`, `description`, `author` fields
- [ ] Repo has at least one `skills/<skill-name>/SKILL.md` with `name:` and `description:` frontmatter
- [ ] Skill descriptions are specific enough to trigger reliably (include example trigger phrases)
- [ ] Skill scanner CI is configured in the team repo (see `ci/skill-scanner/README.md`)
- [ ] Access control is set correctly — only intended team members have read access to the repo
- [ ] Version in `plugin.json` matches the `version` field in the entry below
- [ ] I have added **only** the `plugins[]` entry — I have not modified any other section of `marketplace.json`

### New marketplace.json entry

```json
{
  "name": "<team-name>",
  "source": {
    "source": "git",
    "url": "https://gitlab.company.com/skillshub/<team-name>-skills.git"
  },
  "version": "<version from plugin.json>",
  "description": "<one sentence>",
  "author": {
    "name": "<Team Name>"
  },
  "category": "team",
  "keywords": ["<team-name>", "team"]
}
```

### Team contact

- Team name:
- GitLab group / subgroup for access control:
- Slack channel for questions:
- Who should be added as CODEOWNER for your team's plugin entry (optional):

---

### Checklist (Platform Team reviewer)

- [ ] Team repo is accessible and correctly structured
- [ ] `plugin.json` version matches the entry
- [ ] At least one `SKILL.md` passes the skill scanner
- [ ] Repo access is restricted to the correct team (not world-readable)
- [ ] No sensitive data visible in skill descriptions or plugin.json
- [ ] CODEOWNERS updated if the team requested ownership of their entry

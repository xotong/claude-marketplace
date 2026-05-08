# xotong1 Claude Code Marketplace

Internal Claude Code plugin marketplace for xotong1. v0 — smoke-test only.

## Install (from a Mac with Claude Code)

    /plugin marketplace add https://github.com/xotong/claude-marketplace.git
    /plugin install hello-xotong1@xotong1-marketplace

Then trigger the skill by saying: "test xotong1 marketplace"

## Layout

    .claude-plugin/marketplace.json   The catalog Claude Code reads
    plugins/<plugin>/                 One folder per plugin
        .claude-plugin/plugin.json    Plugin manifest
        skills/<skill>/SKILL.md       The skill itself

## Adding a plugin

1. Create `plugins/<plugin-name>/` following the layout above.
2. Open an MR adding an entry to `.claude-plugin/marketplace.json` under `plugins[]`.
3. Pin the version. Don't reference `main`.

## Phase 2 (not built yet)

- Subgroup split: `catalog/`, `internal/`, `vendored/`, `team-local/`
- CI per skill: lint, semgrep + gitleaks scan, cosign sign, publish to Generic Package Registry
- Vendored upstream skills: superpowers, frontend-design, planning-with-files, systematic-debugging, k8s-troubleshooter, code-reviewer, skill-creator
- `managed-settings.json` pushed to dev laptops with `strictKnownMarketplaces` locked to internal GitLab
- Optional LiteLLM Skills Gateway layer in front of GitLab for centralized auth + per-team filtering

# Vendored Plugins

This file tracks the provenance of plugins vendored from upstream repos.
When updating a vendored plugin, refresh the SHA below, bump the plugin's
version in `.claude-plugin/marketplace.json`, and update the "Vendored on" date.

## Provenance table

| Plugin | Upstream | Vendored at commit | Vendored on | License |
|---|---|---|---|---|
| `superpowers` | https://github.com/obra/superpowers | `f2cbfbefebbfef77321e4c9abc9e949826bea9d7` | 2026-05-08 | MIT |
| `frontend-design` | https://github.com/anthropics/skills (skills/frontend-design) | `d211d437443a7b2496a3dad9575e7dddd724c585` | 2026-05-08 | See `plugins/frontend-design/skills/frontend-design/LICENSE.txt` |
| `anthropic-dev-skills` | https://github.com/anthropics/skills (skills/claude-api, webapp-testing, mcp-builder) | `d211d437443a7b2496a3dad9575e7dddd724c585` | 2026-05-08 | See individual `skills/*/LICENSE.txt` |
| `anthropic-feature-dev` | https://github.com/anthropics/claude-plugins-official (plugins/feature-dev) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `anthropic-pr-review` | https://github.com/anthropics/claude-plugins-official (plugins/pr-review-toolkit) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `anthropic-hookify` | https://github.com/anthropics/claude-plugins-official (plugins/hookify) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `compound-engineering` | https://github.com/EveryInc/compound-engineering-plugin (plugins/compound-engineering) | `6fc57c501f2e4a6978a91b41337026cf25086646` | 2026-05-08 | MIT |

## What was vendored

### superpowers
Upstream root: `.claude-plugin/plugin.json`, `skills/`, `hooks/`, `assets/`, `LICENSE`, `README.md`, `CLAUDE.md`.
Dropped: upstream `marketplace.json`, `.codex-plugin/`, `.cursor-plugin/`, `.opencode/`, `tests/`, `scripts/`, `docs/`.

### frontend-design
`skills/frontend-design/SKILL.md` and `skills/frontend-design/LICENSE.txt` from `anthropics/skills`.
Added `plugins/frontend-design/.claude-plugin/plugin.json` (authored locally — upstream has no per-skill manifest).

### anthropic-dev-skills
`skills/claude-api/`, `skills/webapp-testing/`, `skills/mcp-builder/` from `anthropics/skills` including all reference materials, examples, and language-specific documentation. Added `.claude-plugin/plugin.json` (authored locally).
Note: `skill-creator` from the same repo was not vendored here as a more featureful version is available in `anthropic-official` (claude-plugins-official).

### anthropic-feature-dev
`plugins/feature-dev/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `agents/` (code-architect, code-explorer, code-reviewer), `commands/feature-dev.md`, `LICENSE`, `README.md`.

### anthropic-pr-review
`plugins/pr-review-toolkit/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `agents/` (6 specialised review agents), `commands/`, `LICENSE`, `README.md`.

### anthropic-hookify
`plugins/hookify/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `skills/writing-rules/SKILL.md`, `agents/`, `commands/`, `core/`, `hooks/`, `matchers/`, `utils/`, `LICENSE`, `README.md`.

### compound-engineering
`plugins/compound-engineering/` subtree from `EveryInc/compound-engineering-plugin`.
Contains: `.claude-plugin/plugin.json`, `agents/` (50+ specialised review agents), `skills/` (30+ skills), `LICENSE`, `README.md`, `CHANGELOG.md`, `CLAUDE.md`.
Dropped: `.codex-plugin/plugin.json`, `.cursor-plugin/plugin.json` (other-tool manifests not needed).
Note: `skills/ce-gemini-imagegen/` requires a Google Gemini API key (`GEMINI_API_KEY`) to function. The skill is included but will not work without the key configured on the user's machine.

## Updating a vendored plugin

1. `git clone --depth=1 <upstream-url>` into a temp directory.
2. Compare the relevant subtree against `plugins/<name>/` using `diff -rq`.
3. Copy updated files. Keep all LICENSE files current.
4. Bump `version` in `.claude-plugin/marketplace.json` for the affected plugin.
5. Update the SHA and date in the provenance table above.
6. Open an MR; the Platform Team review covers the diff, not just the bump.

## Security update cadence

- Review each upstream for new releases **quarterly** (first Monday of March, June, September, December).
- If an upstream repo publishes a security advisory, treat it as a P1 and update within 5 business days.
- Upstream security advisories to watch:
  - https://github.com/obra/superpowers/security/advisories
  - https://github.com/anthropics/skills/security/advisories
  - https://github.com/anthropics/claude-plugins-official/security/advisories
  - https://github.com/EveryInc/compound-engineering-plugin/security/advisories

# Vendored Plugins

This file tracks the provenance of plugins vendored from upstream repos. When updating a vendored plugin, refresh the SHA below and bump the plugin's version in `.claude-plugin/marketplace.json`.

| Plugin            | Upstream                                                  | Vendored at commit                         | Vendored on  | License |
| ----------------- | --------------------------------------------------------- | ------------------------------------------ | ------------ | ------- |
| `superpowers`     | https://github.com/obra/superpowers                       | `f2cbfbefebbfef77321e4c9abc9e949826bea9d7` | 2026-05-08   | MIT     |
| `frontend-design` | https://github.com/anthropics/skills (skills/frontend-design) | `d211d437443a7b2496a3dad9575e7dddd724c585` | 2026-05-08   | See `plugins/frontend-design/skills/frontend-design/LICENSE.txt` |

## What was vendored

### superpowers
Copied from upstream root: `.claude-plugin/plugin.json`, `skills/`, `hooks/`, `assets/`, `LICENSE`, `README.md`, `CLAUDE.md`. The upstream `marketplace.json` was dropped (it described upstream's own marketplace, not ours). Other-tool dirs (`.codex-plugin`, `.cursor-plugin`, `.opencode`), tests, scripts, docs, and ecosystem files (`package.json`, `gemini-extension.json`, etc.) were excluded.

The plugin ships a SessionStart hook (`hooks/session-start`) that injects the `using-superpowers` SKILL.md into each Claude Code session as additional context. It is purely additive and side-effect-free.

### frontend-design
Copied just `SKILL.md` and `LICENSE.txt` from `anthropics/skills/skills/frontend-design`. A new `.claude-plugin/plugin.json` was authored locally since the upstream skill ships as part of a larger plugin and has no per-skill manifest.

## Updating a vendored plugin

1. `git clone --depth=1 <upstream>` and diff the relevant subtree against `plugins/<name>/`.
2. Copy the new files in. Keep `LICENSE` files current.
3. Bump `version` in `.claude-plugin/marketplace.json` for the affected plugin.
4. Update the SHA and date row above.

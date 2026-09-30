# Vendored Plugins — self-hosted-model tier

Provenance for the plugins under `plugins/self-hosted/`, copied from this
repo's `VENDORED.md` at the last internal commit before this tier moved out
of the internal repo (`9e4cb36`). `essentials-self-hosted` is Platform
Team's own curated bundle of the plugins below — it has no separate
provenance entry.

## Provenance table

| Plugin | Upstream | Vendored at commit | Vendored on | License |
|---|---|---|---|---|
| `superpowers` | https://github.com/obra/superpowers | `f2cbfbefebbfef77321e4c9abc9e949826bea9d7` | 2026-05-08 | MIT |
| `anthropic-feature-dev` | https://github.com/anthropics/claude-plugins-official (plugins/feature-dev) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `anthropic-pr-review` | https://github.com/anthropics/claude-plugins-official (plugins/pr-review-toolkit) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `compound-engineering` | https://github.com/EveryInc/compound-engineering-plugin (plugins/compound-engineering) | `d8d688b30d97eb5efc3142cec16dd8314ac48e47` | 2026-06-16 | MIT |
| `gstack` | https://github.com/garrytan/gstack | `c7ae63201ab193a7dc7fb7e0d81238645111ffac` | 2026-06-16 | MIT |
| `getshitdone` | https://github.com/gsd-build/get-shit-done | `3aaed8f5d7c3492678b867e6687d42c88fe227e5` | 2026-05-09 | MIT |
| `ruflo` | https://github.com/ruvnet/ruflo | `b5a57cbf1888cc9bfcc68712d3e4679b0e3d7a75` | 2026-05-09 | MIT |
| `agent-skills` | https://github.com/addyosmani/agent-skills | `8c6530305396f341b5da7201cf1f7e390fdb863f` | 2026-07-05 | MIT |

## What was vendored

### superpowers
Upstream root: `.claude-plugin/plugin.json`, `skills/`, `hooks/`, `assets/`, `LICENSE`, `README.md`, `CLAUDE.md`.
Dropped: upstream `marketplace.json`, `.codex-plugin/`, `.cursor-plugin/`, `.opencode/`, `tests/`, `scripts/`, `docs/`.

### anthropic-feature-dev
`plugins/feature-dev/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `agents/` (code-architect, code-explorer, code-reviewer), `commands/feature-dev.md`. (Upstream `LICENSE`/`README.md` were not vendored — corrected 2026-07-05 after the catalog security scan flagged the mismatch.)

### anthropic-pr-review
`plugins/pr-review-toolkit/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `agents/` (6 specialised review agents), `commands/`. (Upstream `LICENSE`/`README.md` were not vendored — corrected 2026-07-05.)

### gstack
Skills from `garrytan/gstack` root (upstream uses flat layout — each skill is a top-level directory).
Contains: 48 skills covering code review, QA, design, planning, browser automation, production safety gates.
Dropped: `openclaw/` (separate sub-package), `bin/`, `extension/` (browser extension), `model-overlays/`, `lib/`, `contrib/` (tooling, not skills).
Added: `.claude-plugin/plugin.json` (authored locally — upstream has no manifest).
Note: `browse`, `qa`, `setup-browser-cookies` skills require Chrome/browser configured on the user's machine.

### getshitdone
Commands from `gsd-build/get-shit-done` `commands/gsd/` directory (66 `/gsd` commands).
Contains: 66 slash commands covering the full Discuss→Plan→Execute→Verify lifecycle plus project management, context management, and team workflows.
Also includes `references/` supporting docs (context-rot patterns, worktree safety, gate prompts, etc.).
Added: `.claude-plugin/plugin.json` (authored locally — upstream has no manifest).

### ruflo
Skills from `ruvnet/ruflo` `.claude/skills/` directory (38 SKILL.md files).
Contains: AgentDB memory skills (learning, vector-search, optimization, memory-patterns), SPARC methodology, swarm orchestration, GitHub automation, pair programming, skill-builder, browser skills.
Dropped: all MCP server configuration (`mcpServers` entries in upstream plugin.json) — swarm coordination features that require `npx claude-flow@alpha`, `npx ruv-swarm`, or `npx flow-nexus@latest` are NOT available in airgapped environments.
Added: simplified `.claude-plugin/plugin.json` (authored locally, without mcpServers).
Note: The 38 skills work fully offline. Swarm MCP features require npx and internet.

### compound-engineering
`plugins/compound-engineering/` subtree from `EveryInc/compound-engineering-plugin`.
Contains: `.claude-plugin/plugin.json`, `agents/` (50+ specialised review agents), `skills/` (30+ skills), `LICENSE`, `README.md`, `CHANGELOG.md`, `CLAUDE.md`.
Dropped: `.codex-plugin/plugin.json`, `.cursor-plugin/plugin.json` (other-tool manifests not needed).
Note: `skills/ce-gemini-imagegen/` requires a Google Gemini API key (`GEMINI_API_KEY`) to function. The skill is included but will not work without the key configured on the user's machine.

### agent-skills
From `addyosmani/agent-skills`: `skills/` (24 skills), `agents/` (4), `references/` (7 shared checklists that skills link to), `hooks/hooks.json` + `hooks/session-start.sh` (SessionStart meta-skill injection; requires `jq`, exits gracefully without it), `LICENSE`. Added `.claude-plugin/plugin.json` (authored locally — upstream manifest lives at repo root and lacks author/hooks fields).
Dropped: `commands/*.toml` (Codex-format), opt-in hook extras `sdd-cache-pre/post.sh` + `SDD-CACHE.md` (use `curl` at runtime) and `simplify-ignore*` (unwired), `session-start-test.sh`, `scripts/`, `docs/`, root README/CLAUDE/AGENTS.
Security modification: simplified `hooks/hooks.json` to drop upstream's fallback that would execute a project-local `.claude/hooks/session-start.sh` (undeclared repo-controlled execution path flagged by the vendoring security scan).
Network notes (kept with documentation, per catalog precedent — ruflo swarm, compound-engineering gemini-imagegen): `source-driven-development` fetches official docs at runtime (works against internal doc mirrors; degrade to vendored references offline); `browser-testing-with-devtools` installs `chrome-devtools-mcp` via npx (works via internal npm mirror); `doubt-driven-development` has an opt-in cross-model step (external Gemini/Codex CLIs, per-run user authorization) — skill works without it.

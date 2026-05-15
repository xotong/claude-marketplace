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
| `obsidian` | https://github.com/kepano/obsidian-skills | `ac9398734fe719565809f7a6048b05c36b1ca38f` | 2026-05-09 | MIT |
| `gstack` | https://github.com/garrytan/gstack | `06605477e25bf9b302888465baec132fa6093f39` | 2026-05-09 | MIT |
| `getshitdone` | https://github.com/gsd-build/get-shit-done | `3aaed8f5d7c3492678b867e6687d42c88fe227e5` | 2026-05-09 | MIT |
| `ruflo` | https://github.com/ruvnet/ruflo | `b5a57cbf1888cc9bfcc68712d3e4679b0e3d7a75` | 2026-05-09 | MIT |

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
Airgap modifications: removed `skills/claude-api/shared/live-sources.md` (dynamic WebFetch URL registry, non-functional offline); updated `skills/claude-api/SKILL.md` to remove references to it. Vendored MCP Python SDK README and TypeScript SDK README into `skills/mcp-builder/reference/` and updated `skills/mcp-builder/SKILL.md` to reference local files instead of raw.githubusercontent.com URLs.

### anthropic-feature-dev
`plugins/feature-dev/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `agents/` (code-architect, code-explorer, code-reviewer), `commands/feature-dev.md`, `LICENSE`, `README.md`.

### anthropic-pr-review
`plugins/pr-review-toolkit/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `agents/` (6 specialised review agents), `commands/`, `LICENSE`, `README.md`.

### anthropic-hookify
`plugins/hookify/` subtree from `anthropics/claude-plugins-official` verbatim.
Contains: `.claude-plugin/plugin.json`, `skills/writing-rules/SKILL.md`, `agents/`, `commands/`, `core/`, `hooks/`, `matchers/`, `utils/`, `LICENSE`, `README.md`.

### obsidian
Full repo from `kepano/obsidian-skills` verbatim (upstream already ships as a Claude plugin).
Contains: `.claude-plugin/plugin.json`, `skills/` (obsidian-markdown, obsidian-bases, obsidian-cli, json-canvas, defuddle), `LICENSE`, `README.md`.
Dropped: upstream `.claude-plugin/marketplace.json` (irrelevant for embedding as a sub-plugin).

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

### First-party (Platform Team authored)

The following skills were authored by the Platform Team and are not vendored from any upstream repo. They have no upstream SHA or license dependency — they are original works owned by the organisation.

| Skill | Added on | Notes |
|---|---|---|
| `appsec-scan` | 2026-05-15 | 7-phase security scan: secrets, SAST, SCA, config review, DAST |
| `lint-and-validate` | 2026-05-15 | Pre-commit gate: auto-fix formatters + linters + type checkers |
| `api-design-principles` | 2026-05-15 | REST/GraphQL design enforcement, RFC 7807, versioning, pagination |
| `openapi-spec-generation` | 2026-05-15 | Generate/sync OpenAPI 3.1 spec with implementation |
| `doc-coauthoring` | 2026-05-15 | Interview-first structured docs: ADR, Design Doc, Runbook, Postmortem |

`lint-and-validate` is also included in `plugins/essentials/` as a mandatory pre-commit gate suitable for all developers.

---

## Updating a vendored source

All upstream sources are now merged into `plugins/platform-verified/` (and `plugins/essentials/` for the curated subset). There are no longer individual `plugins/<name>/` directories.

1. Clone the upstream at the new commit:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   NEW_SHA=$(git -C /tmp/<source-name> rev-parse HEAD)
   ```

2. Identify which files in `plugins/platform-verified/` belong to this source. Check the "What was vendored" section above — each source lists exactly which skill directories it contributed. For example, superpowers contributed `skills/tdd/`, `skills/debugging/`, etc.

3. Remove the old files for this source only, then copy in the new ones:
   ```bash
   # Example: updating superpowers skills
   rm -rf plugins/platform-verified/skills/tdd \
          plugins/platform-verified/skills/debugging \
          plugins/platform-verified/skills/planning  # … all superpowers skills
   cp -r /tmp/<source-name>/skills/. plugins/platform-verified/skills/

   # If this source also contributes to essentials, repeat there:
   rm -rf plugins/essentials/skills/tdd  # … all superpowers skills in essentials
   cp -r /tmp/<source-name>/skills/. plugins/essentials/skills/
   ```

4. Reapply any airgap modifications documented in the "What was vendored" section for this source (e.g., anthropic-dev-skills requires removing `live-sources.md` and keeping the vendored SDK READMEs).

5. Update the SHA and date in the provenance table above.

6. Bump `version` in `plugins/platform-verified/.claude-plugin/plugin.json` (and `plugins/essentials/.claude-plugin/plugin.json` if that plugin was also affected).

7. Open an MR using the **"Add Skill to Platform-Verified"** template. The Platform Team review covers the diff, not just the version bump.

## Security update cadence

- Review each upstream for new releases **quarterly** (first Monday of March, June, September, December).
- If an upstream repo publishes a security advisory, treat it as a P1 and update within 5 business days.
- Upstream security advisories to watch:
  - https://github.com/obra/superpowers/security/advisories
  - https://github.com/anthropics/skills/security/advisories
  - https://github.com/anthropics/claude-plugins-official/security/advisories
  - https://github.com/EveryInc/compound-engineering-plugin/security/advisories
  - https://github.com/kepano/obsidian-skills/security/advisories
  - https://github.com/garrytan/gstack/security/advisories
  - https://github.com/gsd-build/get-shit-done/security/advisories
  - https://github.com/ruvnet/ruflo/security/advisories

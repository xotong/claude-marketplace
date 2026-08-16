# Vendored Plugins

This file tracks the provenance of plugins vendored from upstream repos.
When updating a vendored plugin, refresh the SHA below, bump the plugin's
version in `.claude-plugin/marketplace.json`, and update the "Vendored on" date.

## Provenance table

| Plugin | Upstream | Vendored at commit | Vendored on | License |
|---|---|---|---|---|
| `superpowers` | https://github.com/obra/superpowers | `f2cbfbefebbfef77321e4c9abc9e949826bea9d7` | 2026-05-08 | MIT |
| `frontend-design` | https://github.com/anthropics/skills (skills/frontend-design) | `57546260929473d4e0d1c1bb75297be2fdfa1949` | 2026-06-16 | See `plugins/frontend-design/skills/frontend-design/LICENSE.txt` |
| `anthropic-dev-skills` | https://github.com/anthropics/skills (skills/claude-api, webapp-testing, mcp-builder) | `57546260929473d4e0d1c1bb75297be2fdfa1949` | 2026-06-16 | See individual `skills/*/LICENSE.txt` |
| `anthropic-feature-dev` | https://github.com/anthropics/claude-plugins-official (plugins/feature-dev) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `anthropic-pr-review` | https://github.com/anthropics/claude-plugins-official (plugins/pr-review-toolkit) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `anthropic-hookify` | https://github.com/anthropics/claude-plugins-official (plugins/hookify) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `compound-engineering` | https://github.com/EveryInc/compound-engineering-plugin (plugins/compound-engineering) | `d8d688b30d97eb5efc3142cec16dd8314ac48e47` | 2026-06-16 | MIT |
| `obsidian` | https://github.com/kepano/obsidian-skills | `ac9398734fe719565809f7a6048b05c36b1ca38f` | 2026-05-09 | MIT |
| `gstack` | https://github.com/garrytan/gstack | `c7ae63201ab193a7dc7fb7e0d81238645111ffac` | 2026-06-16 | MIT |
| `getshitdone` | https://github.com/gsd-build/get-shit-done | `3aaed8f5d7c3492678b867e6687d42c88fe227e5` | 2026-05-09 | MIT |
| `ruflo` | https://github.com/ruvnet/ruflo | `b5a57cbf1888cc9bfcc68712d3e4679b0e3d7a75` | 2026-05-09 | MIT |
| `ponytail` | https://github.com/DietrichGebert/ponytail | `16f6cbf4b87792938e47b0f8c650b6d80fcbc98c` | 2026-07-05 | MIT |
| `agent-skills` | https://github.com/addyosmani/agent-skills | `8c6530305396f341b5da7201cf1f7e390fdb863f` | 2026-07-05 | MIT |
| `trailofbits-skills` | https://github.com/trailofbits/skills | `cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af` | 2026-07-05 | CC-BY-SA-4.0 |

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
Airgap modifications: replaced `skills/claude-api/shared/live-sources.md` with an offline stub that tells Claude not to attempt WebFetch and lists the vendored reference files available locally (upstream added many new shared/ files that reference live-sources.md; patching each individually was impractical). Vendored MCP Python SDK README and TypeScript SDK README into `skills/mcp-builder/reference/` and updated `skills/mcp-builder/SKILL.md` to reference local files instead of raw.githubusercontent.com URLs.

### anthropic-feature-dev
`plugins/feature-dev/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `agents/` (code-architect, code-explorer, code-reviewer), `commands/feature-dev.md`. (Upstream `LICENSE`/`README.md` were not vendored — corrected 2026-07-05 after the catalog security scan flagged the mismatch.)

### anthropic-pr-review
`plugins/pr-review-toolkit/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `agents/` (6 specialised review agents), `commands/`. (Upstream `LICENSE`/`README.md` were not vendored — corrected 2026-07-05.)

### anthropic-hookify
`plugins/hookify/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `skills/writing-rules/SKILL.md`, `commands/`, `hooks/`, `matchers/`, `utils/`. (Upstream `agents/`, `core/`, `LICENSE`, `README.md` were not vendored — corrected 2026-07-05.)

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

### ponytail
From `DietrichGebert/ponytail` (v4.8.4): `.claude-plugin/plugin.json` (description prefixed with `[Vendored: …]`, otherwise verbatim), `skills/` (6 skills), `hooks/` (whole dir: claude-codex-hooks.json wiring SessionStart/SubagentStart/UserPromptSubmit node scripts, plus statusline scripts), `LICENSE`.
Dropped: `benchmarks/` (contains `urllib` network code — airgap), `tests/`, `docs/`, `examples/`, `assets/`, `scripts/`, `ponytail-mcp/`, `pi-extension/`, `commands/*.toml` (Codex-format; the skills already cover the /ponytail-* triggers), all other-harness dirs (`.cursor`, `.codex-plugin`, `.windsurf`, `.openclaw`, `.opencode`, `.devin-plugin`, `.kiro`, `.clinerules`, `.agents`, `.github`), root README/AGENTS/package.json.
Runtime note: hooks execute via `node` (local file I/O only — no network).
Airgap modifications: rewrote the `ponytail-help` "Update" section (upstream instructed marketplace auto-update + `npm install -g` — internet-dependent and stale for a vendored copy) and pointed the `ponytail-gain` benchmark-source line at upstream instead of the dropped local `benchmarks/` dir.

### agent-skills
From `addyosmani/agent-skills`: `skills/` (24 skills), `agents/` (4), `references/` (7 shared checklists that skills link to), `hooks/hooks.json` + `hooks/session-start.sh` (SessionStart meta-skill injection; requires `jq`, exits gracefully without it), `LICENSE`. Added `.claude-plugin/plugin.json` (authored locally — upstream manifest lives at repo root and lacks author/hooks fields).
Dropped: `commands/*.toml` (Codex-format), opt-in hook extras `sdd-cache-pre/post.sh` + `SDD-CACHE.md` (use `curl` at runtime) and `simplify-ignore*` (unwired), `session-start-test.sh`, `scripts/`, `docs/`, root README/CLAUDE/AGENTS.
Security modification: simplified `hooks/hooks.json` to drop upstream's fallback that would execute a project-local `.claude/hooks/session-start.sh` (undeclared repo-controlled execution path flagged by the vendoring security scan).
Network notes (kept with documentation, per catalog precedent — ruflo swarm, compound-engineering gemini-imagegen): `source-driven-development` fetches official docs at runtime (works against internal doc mirrors; degrade to vendored references offline); `browser-testing-with-devtools` installs `chrome-devtools-mcp` via npx (works via internal npm mirror); `doubt-driven-development` has an opt-in cross-model step (external Gemini/Codex CLIs, per-run user authorization) — skill works without it.

### trailofbits-skills
Curated subset of `trailofbits/skills` (upstream is a 40-plugin monorepo under `plugins/`). Merged 17 sub-plugins into one plugin — `skills/` (33), `commands/` (6), `agents/` (13), no name collisions: audit-context-building, differential-review, entry-point-analyzer, variant-analysis, static-analysis (codeql/semgrep/sarif-parsing), semgrep-rule-creator, semgrep-rule-variant-creator, fp-check, insecure-defaults, sharp-edges, supply-chain-risk-auditor, agentic-actions-auditor, spec-to-code-compliance, property-based-testing, mutation-testing, dimensional-analysis, testing-handbook-skills (15 fuzzing/testing skills). Added `.claude-plugin/plugin.json` (authored locally). Kept upstream `LICENSE`.
Excluded sub-plugins: `c-review`, `rust-review` (plugin-root `prompts/`+`scripts/` collide when flattened; C/C++/Rust off-stack internally), `constant-time-analysis` (bundled Python package needing `uv` install — airgap), `zeroize-audit`, `yara-authoring`, `dwarf-expert`, `seatbelt-sandboxer`, `firebase-apk-scanner`, `burpsuite-project-parser`, `building-secure-contracts` (niche/off-mission), `debug-buttercup`, `culture-index`, `trailmark`, `let-fate-decide`, `claude-in-chrome-troubleshooting`, `second-opinion` (Trail of Bits-internal/situational), `gh-cli`, `git-cleanup`, `devcontainer-setup`, `modern-python`, `ask-questions-if-underspecified`, `skill-improver`, `workflow-skill-design` (off security theme or overlap with existing catalog).
License note: CC-BY-SA-4.0 — attribution kept via LICENSE + this entry; share-alike applies to derivative modifications of the skill content.
Network notes (kept with documentation, per catalog precedent): `semgrep-rule-creator` mandates WebFetch of semgrep-docs URLs before writing rules (works via internal doc mirror/proxy; unusable fully offline); `testing-handbook-generator` fetches external resources and installs its validator via `uv pip`; the fuzzing skills (aflpp, atheris, cargo-fuzz, libafl, libfuzzer, ossfuzz, ruzzy) document fuzzer/toolchain installs (apt/pip/cargo/rustup) as prerequisites — use internal mirrors. Scan/audit skills (semgrep, codeql, sarif-parsing, agentic-actions-auditor, supply-chain-risk-auditor) default to locally installed tools and offline/local modes; `merge_sarif.py` uses `npx --no-install` (never downloads).

### First-party (Platform Team authored)

The following skills were authored by the Platform Team and are not vendored from any upstream repo. They have no upstream SHA or license dependency — they are original works owned by the organisation.

| Skill | Added on | Notes |
|---|---|---|
| `appsec-scan` | 2026-05-20 | Container-based CI-mirror: 4 components from lobster-thermidor/devops/ci-catalogue (Fortify SCA SAST, Dependency Scanning SBOM, Secret Detection, Container Scanning). Refactored to v3.0.0 on 2026-07-15 (removed Parasoft, Pylint, ESLint, Scantist, Trivy, GitLab Semgrep SAST). **v3.3.0 (2026-08-08)** makes `image:`/`runner:` optional and derives the scanner image from the component template — the vendored snapshots below are now load-bearing, not just an offline fallback. Vendored catalog snapshots: see section below. |
| `appsec-dast-sim` | 2026-05-20 | LLM-based DAST following WSTG v4.2; no containers required; works at design time |
| `lint-and-validate` | 2026-05-15 | Pre-commit gate: auto-fix formatters + linters + type checkers |
| `api-design-principles` | 2026-05-15 | REST/GraphQL design enforcement, RFC 7807, versioning, pagination |
| `openapi-spec-generation` | 2026-05-15 | Generate/sync OpenAPI 3.1 spec with implementation |
| `doc-coauthoring` | 2026-05-15 | Interview-first structured docs: ADR, Design Doc, Runbook, Postmortem |

`lint-and-validate` is also included in `plugins/essentials/` as a mandatory pre-commit gate suitable for all developers.

### appsec-scan: vendored CI/CD Catalog snapshots

The `appsec-scan` skill vendors offline fallback snapshots of 4 GitLab CI/CD Catalog components from the private group `lobster-thermidor/devops/ci-catalogue` on gitlab.com. Snapshots live under `plugins/appsec/skills/appsec-scan/reference/catalog/lobster-thermidor/devops/ci-catalogue/`.

| Component | Tag | Fetched | Source |
|---|---|---|---|
| `lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast` | 25.2.0, 25.2.1 | 2026-08-16 | gitlab.com (private, authenticated fetch) |
| `lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning` | 1.0.0, 1.1.0, 1.2.0, 1.3.1 | 2026-08-16 | gitlab.com (private, authenticated fetch) |
| `lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection` | 1.0.0 | 2026-08-16 | gitlab.com (private, authenticated fetch) |
| `lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning` | 1.0.0, 1.1.0 | 2026-08-16 | gitlab.com (private, authenticated fetch) |

Each tag directory also carries a `.commit` stamp recording the commit the snapshot came from, so a tag that is later MOVED onto different content is reported as `DRIFT:` instead of being served stale from the offline fallback. `fortify-sast@25.2.0` was re-tagged exactly that way on 2026-08-15.

Each snapshot includes `template.yml`, `README.md`, and `AGENTS.md`. Prior tag directories are kept; the resolver picks the highest. Refresh snapshots quarterly per UPDATE-GUIDE.md Scenario 6, and regenerate `plugins/appsec/skills/appsec-scan/scanners/*.contract` at the same time so component input/report drift keeps being detected.

**Note:** `fortify-sast@25.2.0` was re-fetched on 2026-07-25. The earlier copy had been taken partly from HEAD and predated the component's registry move — it still named `…/ci-catalogue/fortify-sast/` for scanner images, whereas the tag now declares `…/ci-catalogue/docker-images/`. The `fortify-sast` project has no container registry of its own; all images live in the `docker-images` project.

**Since v3.3.0 these snapshots decide which image runs**, not just what the offline fallback says: with `image:` omitted (how both profiles now ship), `catalog.sh template-image` reads the scanner image out of `template.yml`. A snapshot vendored from gitlab.com therefore names gitlab.com's registry — an airgapped estate must re-vendor from its own instance (`scripts/revendor.sh`) before rollout. `revendor.sh` refuses to vendor a component that resolved `[offline-fallback]`, so a stale snapshot cannot confirm itself.

#### Known defects INSIDE these snapshots — do not "fix" them here

Automated security review flags `curl -k` in `dependency-scanning/.../template.yml` on every re-vendor. It is a real defect, and it is **deliberately left byte-identical to upstream**:

- A snapshot that differs from upstream makes the drift gate compare runners against fiction — the same false-clean these snapshots exist to prevent, and the same rule as *never hand-edit a contract to silence drift*.
- It is not reachable through this skill. The line lives in the component's `<job-name>-python` **resolution** job; `scanners/gitlab-dependency-scanning.sh` runs `/analyzer run` and invokes no installer at all.
- This skill's own runner does not copy the pattern: `scanners/fortify-sast.sh` verifies, then tries the configured CA, and reaches `-k` only behind `settings.python_runtime.allow_insecure_uv_download` (off by default), announcing every use as `APPSEC-INSECURE-TLS`.

Tracked upstream at `dependency-scanning#3`. It was previously "part 2" of that project's `#1`, which was closed while the defect remained — which is why it now has an issue of its own.

### appsec-scan: catalogue components deliberately NOT covered

Four more components exist in `lobster-thermidor/devops/ci-catalogue`. Recording the status here so it is not re-derived each time someone notices the gap:

| Component | Status | Reason |
|---|---|---|
| `dast` | **Declined** | Needs a deployed, running, authenticated target — a URL plus login selectors or a Playwright script. A pre-push scan of a working tree has nothing to point it at. |
| `api-security` | **Declined** | Same blocker, harder: `target-url` is a mandatory input. |
| `sgx` (Semgrep Extended SAST) | Not covered | No decision recorded — open if a team asks for it. |
| `srm-report-upload` | Not covered | Uploads results to SRM. appsec-scan is scan-only by design: nothing leaves `.appsec-results/`. The `fortify-sast` component includes it for its own CI upload job. |

The design-time intent behind `dast` / `api-security` is already served by the `appsec-dast-sim` skill, which reads the codebase instead of probing a deployment. Both remain the right tool **in CI**, after a deploy job. See [`plugins/appsec/skills/appsec-scan/docs/ARCHITECTURE.md`](plugins/appsec/skills/appsec-scan/docs/ARCHITECTURE.md#catalogue-components-this-skill-does-not-cover).

---

## Updating a vendored source

Each upstream source lives in its own plugin directory under `plugins/<source-name>/`.

1. Clone the upstream at the new commit:
   ```bash
   git clone --depth=1 <upstream-url> /tmp/<source-name>
   NEW_SHA=$(git -C /tmp/<source-name> rev-parse HEAD)
   ```

2. Replace the content in the plugin directory:
   ```bash
   rm -rf plugins/<source-name>/skills/*
   cp -r /tmp/<source-name>/skills/. plugins/<source-name>/skills/

   # If this source also contributes to essentials, update that too:
   rm -rf plugins/essentials/skills/<affected-skill>  # repeat for each skill
   cp -r /tmp/<source-name>/skills/. plugins/essentials/skills/
   ```

3. Reapply any airgap modifications documented in the "What was vendored" section for this source (e.g., anthropic-dev-skills requires removing `live-sources.md` and keeping the vendored SDK READMEs).

4. Update the SHA and date in the provenance table above.

5. Bump `version` in `plugins/<source-name>/.claude-plugin/plugin.json` (and `plugins/essentials/.claude-plugin/plugin.json` if that plugin was also affected).

6. Open an MR using the **"Add Vendored Plugin"** template. The Platform Team review covers the diff, not just the version bump.

## Revendoring status (as of 2026-06-16)

High-priority plugins revendored on 2026-06-16. Remaining medium/low-priority plugins checked against upstream HEAD.

| Plugin | Status | Priority | Notes |
|---|---|---|---|
| `anthropic-dev-skills` / `frontend-design` | ✅ Revendored 2026-06-16 @ `5754626` | **High** | New model support (Fable 5, Opus 4.8), Managed Agents updates |
| `compound-engineering` | ✅ Revendored 2026-06-16 @ `d8d688b` (v3.13.0) | **High** | 79-commit update; LFG workflow fix, 39 skills + 43 agents |
| `gstack` | ✅ Revendored 2026-06-16 @ `c7ae632` | **High** | 56-commit update; added iOS skills, diagram, spec, skillify; removed 9 deprecated skills |
| `obsidian` | Deferred | Low | Minor docs/example additions only |
| `superpowers` | Deferred | Low | Contributor policy + job posting only; no skill content changes |
| `anthropic-feature-dev` / `anthropic-pr-review` / `anthropic-hookify` | Deferred | Medium | Check only the vendored subdirs (`plugins/feature-dev`, `plugins/pr-review-toolkit`, `plugins/hookify`) before revendoring |
| `getshitdone` | Deferred | Medium | Evaluate skill quality before revendoring at this scale |
| `ruflo` | Deferred | Medium | Evaluate skill quality before revendoring at this scale |

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

# Vendored Plugins

This file tracks the provenance of plugins vendored from upstream repos.
When updating a vendored plugin, refresh the SHA below, bump the plugin's
version in `.claude-plugin/marketplace.json`, and update the "Vendored on" date.

## Provenance table

| Plugin | Upstream | Vendored at commit | Vendored on | License |
|---|---|---|---|---|
| `frontend-design` | https://github.com/anthropics/skills (skills/frontend-design) | `57546260929473d4e0d1c1bb75297be2fdfa1949` | 2026-06-16 | See `plugins/frontend-design/skills/frontend-design/LICENSE.txt` |
| `anthropic-dev-skills` | https://github.com/anthropics/skills (skills/claude-api, webapp-testing, mcp-builder) | `57546260929473d4e0d1c1bb75297be2fdfa1949` | 2026-06-16 | See individual `skills/*/LICENSE.txt` |
| `anthropic-hookify` | https://github.com/anthropics/claude-plugins-official (plugins/hookify) | `76b35e91d1c99c090b1a08dade53bcc5e352c1b2` | 2026-05-08 | MIT |
| `obsidian` | https://github.com/kepano/obsidian-skills | `ac9398734fe719565809f7a6048b05c36b1ca38f` | 2026-05-09 | MIT |
| `ponytail` | https://github.com/DietrichGebert/ponytail | `16f6cbf4b87792938e47b0f8c650b6d80fcbc98c` | 2026-07-05 | MIT |
| `trailofbits-skills` | https://github.com/trailofbits/skills | `cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af` | 2026-07-05 | CC-BY-SA-4.0 |
| `claude-security` | https://github.com/anthropics/claude-plugins-official (plugins/claude-security) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Proprietary — Anthropic, internal use only (see below) |
| `security-guidance` | https://github.com/anthropics/claude-plugins-official (plugins/security-guidance) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `pyright-lsp` | https://github.com/anthropics/claude-plugins-official (plugins/pyright-lsp) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `typescript-lsp` | https://github.com/anthropics/claude-plugins-official (plugins/typescript-lsp) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `gopls-lsp` | https://github.com/anthropics/claude-plugins-official (plugins/gopls-lsp) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `jdtls-lsp` | https://github.com/anthropics/claude-plugins-official (plugins/jdtls-lsp) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `code-modernization` | https://github.com/anthropics/claude-plugins-official (plugins/code-modernization) | `2a8ad9f74633d10e3d9bb0660a03bfc6e50584b1` | 2026-09-30 | Apache-2.0 |
| `skill-scanner` | https://github.com/getsentry/skills (skills/skill-scanner) | `d18b7aa8ba878354e5c348310230e652f7690f9c` | 2026-09-30 | Apache-2.0 |

## What was vendored

### frontend-design
`skills/frontend-design/SKILL.md` and `skills/frontend-design/LICENSE.txt` from `anthropics/skills`.
Added `plugins/frontend-design/.claude-plugin/plugin.json` (authored locally — upstream has no per-skill manifest).

### anthropic-dev-skills
`skills/claude-api/`, `skills/webapp-testing/`, `skills/mcp-builder/` from `anthropics/skills` including all reference materials, examples, and language-specific documentation. Added `.claude-plugin/plugin.json` (authored locally).
Note: `skill-creator` from the same repo was not vendored here as a more featureful version is available in `anthropic-official` (claude-plugins-official).
Local modifications: replaced `skills/claude-api/shared/live-sources.md` with an offline stub that tells Claude not to attempt WebFetch and lists the vendored reference files available locally (upstream added many new shared/ files that reference live-sources.md; patching each individually was impractical). Vendored MCP Python SDK README and TypeScript SDK README into `skills/mcp-builder/reference/` and updated `skills/mcp-builder/SKILL.md` to reference local files instead of raw.githubusercontent.com URLs.

### anthropic-hookify
`plugins/hookify/` subtree from `anthropics/claude-plugins-official`.
Contains: `.claude-plugin/plugin.json`, `skills/writing-rules/SKILL.md`, `commands/`, `hooks/`, `matchers/`, `utils/`. (Upstream `agents/`, `core/`, `LICENSE`, `README.md` were not vendored — corrected 2026-07-05.)

### obsidian
Full repo from `kepano/obsidian-skills` verbatim (upstream already ships as a Claude plugin).
Contains: `.claude-plugin/plugin.json`, `skills/` (obsidian-markdown, obsidian-bases, obsidian-cli, json-canvas, defuddle), `LICENSE`, `README.md`.
Dropped: upstream `.claude-plugin/marketplace.json` (irrelevant for embedding as a sub-plugin).

### ponytail
From `DietrichGebert/ponytail` (v4.8.4): `.claude-plugin/plugin.json` (description prefixed with `[Vendored: …]`, otherwise verbatim), `skills/` (6 skills), `hooks/` (whole dir: claude-codex-hooks.json wiring SessionStart/SubagentStart/UserPromptSubmit node scripts, plus statusline scripts), `LICENSE`.
Dropped: `benchmarks/` (makes network calls via `urllib`), `tests/`, `docs/`, `examples/`, `assets/`, `scripts/`, `ponytail-mcp/`, `pi-extension/`, `commands/*.toml` (Codex-format; the skills already cover the /ponytail-* triggers), all other-harness dirs (`.cursor`, `.codex-plugin`, `.windsurf`, `.openclaw`, `.opencode`, `.devin-plugin`, `.kiro`, `.clinerules`, `.agents`, `.github`), root README/AGENTS/package.json.
Runtime note: hooks execute via `node` (local file I/O only — no network).
Local modifications: rewrote the `ponytail-help` "Update" section (upstream instructed marketplace auto-update + `npm install -g` — internet-dependent and stale for a vendored copy) and pointed the `ponytail-gain` benchmark-source line at upstream instead of the dropped local `benchmarks/` dir.

### trailofbits-skills
Curated subset of `trailofbits/skills` (upstream is a 40-plugin monorepo under `plugins/`). Merged 17 sub-plugins into one plugin — `skills/` (33), `commands/` (6), `agents/` (13), no name collisions: audit-context-building, differential-review, entry-point-analyzer, variant-analysis, static-analysis (codeql/semgrep/sarif-parsing), semgrep-rule-creator, semgrep-rule-variant-creator, fp-check, insecure-defaults, sharp-edges, supply-chain-risk-auditor, agentic-actions-auditor, spec-to-code-compliance, property-based-testing, mutation-testing, dimensional-analysis, testing-handbook-skills (15 fuzzing/testing skills). Added `.claude-plugin/plugin.json` (authored locally). Kept upstream `LICENSE`.
Excluded sub-plugins: `c-review`, `rust-review` (plugin-root `prompts/`+`scripts/` collide when flattened; C/C++/Rust off-stack internally), `constant-time-analysis` (bundled Python package needing `uv` install), `zeroize-audit`, `yara-authoring`, `dwarf-expert`, `seatbelt-sandboxer`, `firebase-apk-scanner`, `burpsuite-project-parser`, `building-secure-contracts` (niche/off-mission), `debug-buttercup`, `culture-index`, `trailmark`, `let-fate-decide`, `claude-in-chrome-troubleshooting`, `second-opinion` (Trail of Bits-internal/situational), `gh-cli`, `git-cleanup`, `devcontainer-setup`, `modern-python`, `ask-questions-if-underspecified`, `skill-improver`, `workflow-skill-design` (off security theme or overlap with existing catalog).
License note: CC-BY-SA-4.0 — attribution kept via LICENSE + this entry; share-alike applies to derivative modifications of the skill content.
Network notes (kept with documentation, per catalog precedent): `semgrep-rule-creator` mandates WebFetch of semgrep-docs URLs before writing rules (works via internal doc mirror/proxy; unusable fully offline); `testing-handbook-generator` fetches external resources and installs its validator via `uv pip`; the fuzzing skills (aflpp, atheris, cargo-fuzz, libafl, libfuzzer, ossfuzz, ruzzy) document fuzzer/toolchain installs (apt/pip/cargo/rustup) as prerequisites — use internal mirrors. Scan/audit skills (semgrep, codeql, sarif-parsing, agentic-actions-auditor, supply-chain-risk-auditor) default to locally installed tools and offline/local modes; `merge_sarif.py` uses `npx --no-install` (never downloads).

### claude-security
Full `plugins/claude-security/` subtree from `anthropics/claude-plugins-official`, copied verbatim/unmodified: `.claude-plugin/plugin.json`, `.gitattributes`, `LICENSE`, `NOTICE.md`, `README.md`, `SECURITY.md`, `agents/` (7 agent defs), `hooks/`, `scripts/` (incl. `scripts/lib/`), `skills/claude-security/` (SKILL.md + jobs/ + specs/), `workflows/scan.js`. Nothing dropped.

**License — proprietary, not open source.** `LICENSE` grants "a limited, non-exclusive, non-transferable, non-sublicensable, revocable license to install, run, and modify the Plugin for your internal use, solely with Claude Code or other Anthropic products and services," and forbids distributing the Plugin or any modified version to any third party, and forbids using it with, or to develop, any non-Anthropic product or service. The Platform Team has decided that installs by tenants of this internal marketplace fall within "internal use" under that grant. Two consequences follow directly from the license text, not just from internal policy: this plugin must **never** be run against, or packaged for use with, a non-Anthropic model — it is Claude-only by license, not merely by convenience — and it is **excluded from the public GitHub mirror**. `ci/publish-github.sh` strips `plugins/claude-security/` and its marketplace entry out of the exported tree, and removes `claude-security` from the `dependencies` array of any exported `plugin.json` (a future essentials-style bundle must not silently pull it in via that path).

Runtime note: Claude models only — the multi-agent scan/patch workflow runs entirely inside the Claude Code session under the session's own model; no separate infrastructure, but inherently bound to Anthropic models by both the license and the design.

### security-guidance
`plugins/security-guidance/` subtree from `anthropics/claude-plugins-official`: `.claude-plugin/plugin.json`, `LICENSE` (Apache-2.0), `README.md`, `hooks/` (pattern-based edit warnings, LLM Stop-hook diff review, agentic commit reviewer).
Dropped: `tests/` (pytest suite, not needed at runtime).
**Local modification:** `hooks/sg-python.sh` exports `SSL_CERT_FILE` (unless already set) to a bundle cached at `~/.claude/security/ca-bundle.pem`: on macOS the system roots plus the System keychain, in WSL the distro's CA bundle plus the Windows trusted roots (via `powershell.exe`). Behind Zscaler, upstream's Python could not verify the proxy's certificate, so every LLM review failed with `CERTIFICATE_VERIFY_FAILED` after ~18 s of retries (72 failures in one developer's log). Native Windows and plain Linux Python already trust the OS store, so the patch does nothing there. Re-apply it when re-vendoring.
Runtime note: Claude only, and internet-connected — `hooks/ensure_agent_sdk.py` pip-installs `claude-agent-sdk` from PyPI at session start, and the Stop-hook diff review plus the agentic commit reviewer each send that turn's diff to the Anthropic API for review. Without internet access the SDK bootstrap and review calls fail closed.

### pyright-lsp / typescript-lsp / gopls-lsp / jdtls-lsp
Each ← `anthropics/claude-plugins-official` `plugins/<name>/`, which upstream ships as `LICENSE` (Apache-2.0) + `README.md` only — the manifest (`name`, `version`, `lspServers`, etc.) lives inline in upstream's `.claude-plugin/marketplace.json`, not as a per-plugin `plugin.json`. Copied `LICENSE` + `README.md` verbatim from each upstream plugin dir; authored `plugins/<name>/.claude-plugin/plugin.json` locally from that inline marketplace object, keeping `name`, `description`, `version`, `author`, `lspServers` exactly as upstream defines them and dropping the marketplace-only `source`, `category`, `strict` keys (checked against every other `plugin.json` in this repo — none use those three keys, confirming they are marketplace-listing fields, not plugin manifest fields).
Runtime note: each needs its language-server binary on `PATH`, installed by the developer — `pyright-lsp` → `pyright-langserver` (`npm install -g pyright`, or `pip`/`pipx install pyright`); `typescript-lsp` → `typescript-language-server` (`npm install -g typescript-language-server typescript`); `gopls-lsp` → `gopls` (`go install golang.org/x/tools/gopls@latest`); `jdtls-lsp` → `jdtls` + JDK 17+ (`brew install jdtls` on macOS, or a manual Eclipse JDT.LS install elsewhere). None of the four make network calls themselves once their binary is installed — the LSP process runs locally.

### code-modernization
Full `plugins/code-modernization/` subtree from `anthropics/claude-plugins-official`, copied unmodified: `.claude-plugin/plugin.json`, `LICENSE` (Apache-2.0), `README.md`, `CHANGELOG.md`, `agents/` (7), `assets/` (incl. `assets/vendor/LICENSE-mermaid.txt` and `assets/vendor/mermaid.min.js`), `commands/` (13 `/modernize-*` commands), `hooks/` (TypeScript live-progress pane), `scripts/` (Python analysis/report tooling, incl. `scripts/tests/`), `tests/` (TS test suite + fixtures), `tsconfig.json`, `workflows/` (5 `.js` entry points). Nothing dropped.
Runtime note: offline — every command reads/writes the local `analysis/` tree; the optional live-progress pane and all Python/TS tooling run locally with no network calls.

### skill-scanner
`skills/skill-scanner/` from `getsentry/skills`: `SKILL.md`, `references/` (`dangerous-code-patterns.md`, `permission-analysis.md`, `prompt-injection-patterns.md`), `scripts/scan_skill.py`. Placed at `plugins/skill-scanner/skills/skill-scanner/` — upstream ships this as one skill inside a flat, repo-wide `sentry-skills` plugin with no per-skill manifest, so `plugins/skill-scanner/.claude-plugin/plugin.json` was authored locally (name `skill-scanner`, version `1.0.0`, author Sentry). Copied the upstream repo-root `LICENSE` (Apache-2.0) into `plugins/skill-scanner/LICENSE`.
Runtime note: offline static analysis. The bundled `scripts/scan_skill.py` is invoked as `uv run scripts/scan_skill.py <skill-directory>`, so the `uv` CLI must be on `PATH`; the SKILL.md workflow falls back to manual Grep-based analysis if the script is unavailable.

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

**Since v3.3.0 these snapshots decide which image runs**, not just what the offline fallback says: with `image:` omitted (how both profiles now ship), `catalog.sh template-image` reads the scanner image out of `template.yml`. A snapshot vendored from gitlab.com therefore names gitlab.com's registry — a network-isolated estate must re-vendor from its own instance (`scripts/revendor.sh`) before rollout. `revendor.sh` refuses to vendor a component that resolved `[offline-fallback]`, so a stale snapshot cannot confirm itself.

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

3. Reapply any local modifications documented in the "What was vendored" section for this source (e.g., anthropic-dev-skills requires removing `live-sources.md` and keeping the vendored SDK READMEs).

4. Update the SHA and date in the provenance table above.

5. Bump `version` in `plugins/<source-name>/.claude-plugin/plugin.json` (and `plugins/essentials/.claude-plugin/plugin.json` if that plugin was also affected).

6. Open an MR using the **"Add Vendored Plugin"** template. The Platform Team review covers the diff, not just the version bump.

## Revendoring status (as of 2026-06-16)

High-priority plugins revendored on 2026-06-16. Remaining medium/low-priority plugins checked against upstream HEAD.

| Plugin | Status | Priority | Notes |
|---|---|---|---|
| `anthropic-dev-skills` / `frontend-design` | ✅ Revendored 2026-06-16 @ `5754626` | **High** | New model support (Fable 5, Opus 4.8), Managed Agents updates |
| `obsidian` | Deferred | Low | Minor docs/example additions only |
| `anthropic-hookify` | Deferred | Medium | Check only the vendored subdir (`plugins/hookify`) before revendoring |

## Security update cadence

- Review each upstream for new releases **quarterly** (first Monday of March, June, September, December).
- If an upstream repo publishes a security advisory, treat it as a P1 and update within 5 business days.
- Upstream security advisories to watch:
  - https://github.com/anthropics/skills/security/advisories
  - https://github.com/anthropics/claude-plugins-official/security/advisories
  - https://github.com/kepano/obsidian-skills/security/advisories

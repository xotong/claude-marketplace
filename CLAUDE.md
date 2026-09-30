# Claude Code — Contributor Context

This is the `platform-engineering/skillshub/claude-marketplace` repo. It is the Platform Team's curated skill catalog for Claude Code running against Anthropic's Claude models. It does **not** host team-specific skills — each team runs its own private marketplace.

## Repo structure

```
.claude-plugin/marketplace.json   Central catalog (Platform Team only) — name: platform-claude-marketplace
plugins/
  essentials/                     Dependency-only bundle — dependencies: [appsec, code-quality, claude-security, security-guidance, 4 LSPs]
  appsec/                         Platform Team — appsec-scan, appsec-dast-sim, security-options
  code-quality/                   Platform Team — 4 code/doc quality skills
  claude-security/                Vendored: Anthropic — deep vuln scan + patch loop (Claude models only)
  security-guidance/              Vendored: Anthropic — edit-time + end-of-turn LLM review (needs internet + API)
  pyright-lsp/                    Vendored: Anthropic — Python language server
  typescript-lsp/                 Vendored: Anthropic — TypeScript/JS language server
  gopls-lsp/                      Vendored: Anthropic — Go language server
  jdtls-lsp/                      Vendored: Anthropic — Java language server
  code-modernization/             Vendored: Anthropic — guided legacy modernization
  skill-scanner/                  Vendored: getsentry/skills — pre-install skill/plugin scanner
  anthropic-dev-skills/           Vendored: anthropics/skills (4 skills)
  obsidian/                       Vendored: kepano/obsidian-skills (5 skills)
  anthropic-hookify/              Vendored: anthropics/claude-plugins-official (hookify)
  frontend-design/                Vendored: anthropics/skills (frontend-design)
  ponytail/                       Vendored: DietrichGebert/ponytail (6 skills + mode hooks)
  trailofbits-skills/             Vendored: trailofbits/skills (33 skills, curated subset)
VENDORED.md                       Upstream SHAs, licenses, what was included/excluded
CODEOWNERS                        Approval rules (GitLab Ultimate [Section][N] syntax)
```

## Claude-only, 17-plugin catalog

The marketplace (registered as `platform-claude-marketplace`) offers 17 installable plugins for Claude Code against Claude models. Claude Code's own built-ins (plan mode, `/code-review`, `/security-review`) cover planning and review, so this catalog doesn't duplicate them:

- **`essentials`** — dependency-only bundle (2.0.0): installing it installs `appsec`, `code-quality`, `claude-security`, `security-guidance` and the four LSP plugins. Install this first.
- **`appsec`** — Platform Team security scanning: appsec-scan (Fortify SAST + more), appsec-dast-sim, security-options (routing)
- **`code-quality`** — Platform Team code/doc quality tools
- **`claude-security`** — deep vulnerability hunt + patch loop. Proprietary Anthropic licence: internal use only, solely with Claude Code/Anthropic products, excluded from the public GitHub mirror
- **`security-guidance`** — edit-time pattern warnings + end-of-turn LLM diff review. Needs internet and the Anthropic API
- **`pyright-lsp` / `typescript-lsp` / `gopls-lsp` / `jdtls-lsp`** — language servers; each needs its binary on `PATH` (one-time install)
- **`code-modernization`** — guided legacy-codebase modernization (offline)
- **`skill-scanner`** — scans a skill/plugin for prompt-injection/supply-chain risk before install (offline)
- **6 more vendored plugins** — `anthropic-dev-skills`, `obsidian`, `anthropic-hookify`, `frontend-design`, `ponytail`, `trailofbits-skills`

## Vendored sources

Each upstream source has its own plugin directory: `plugins/<source-name>/`. See `VENDORED.md` for upstream SHAs and what was included from each source.

## Network requirements

Vendored content makes no runtime network calls unless its description says so. Do not add, anywhere under `plugins/`:
- Runtime `WebFetch` instructions in SKILL.md files that point to external URLs
- `live-sources.md` style dynamic URL registries
- Skills that `npx`-install packages at runtime (or document clearly that they require internet)

Some plugins need internet, but only when listed explicitly here and in the plugin's own description:
- **`security-guidance`** — pip-installs `claude-agent-sdk` from PyPI at session start and sends each turn's diff to the Anthropic API for an LLM review. Installed with essentials. Its launcher is patched locally to trust a TLS-inspecting proxy's root (see VENDORED.md).
- **`pyright-lsp` / `typescript-lsp` / `gopls-lsp` / `jdtls-lsp`** — need a one-time install of their language-server binary onto `PATH`; the servers themselves then run locally.
- **`claude-security`** — runs entirely inside the Claude Code session; excluded from the public GitHub mirror per its licence.

MCP SDK docs and other reference material should be vendored locally under `skills/<name>/reference/`.

**Narrow exception — appsec-scan catalog integration:** the `appsec-scan` skill's helper scripts (`scripts/catalog.sh`, `scripts/glci-run.sh`, `scripts/remote-match.sh`) may make runtime calls to the single GitLab instance configured in `config/scanner-preferences.yaml` (`gitlab_instance`; the `catalog` profile points at gitlab.com, the `company` and `platform-engineering` profiles at internal instances). `catalog.sh` fetches CI/CD Catalog metadata (tags, component templates, READMEs, AGENTS.md) for version resolution and drift warnings. `glci-run.sh` (profile `engine: glci`) additionally resolves the catalog component's own CI includes and pulls its own runner images to run the real job locally. `remote-match.sh` (profile `remote_match_project` set) uploads only dependency manifests/lockfiles to that configured helper project and pulls back its GitLab-native dependency-scanning report. The skill must keep working fully offline — via the vendored snapshots in `plugins/appsec/skills/appsec-scan/reference/catalog/lobster-thermidor/devops/ci-catalogue/`, the docker engine, and offline Trivy matching (`APPSEC_REMOTE_MATCH=off` forces this path even when `remote_match_project` is set) — never add WebFetch instructions to SKILL.md prose.

## Skill security scan

CI runs SkillSpector (NVIDIA, Apache-2.0) via the `platform-engineering/ci-catalogue/skillspector` GitLab CI/CD component — static-only analysis, no runtime LLM calls. It is report-only (`fail_on: none`) while SkillSpector's accuracy is under review. MR pipelines scan only changed skills; web and scheduled pipelines scan everything.

## Adding a new upstream source

See README.md "For contributors" section for the full step-by-step. Short version:
1. Clone upstream into `/tmp/<source-name>`
2. Create `plugins/<source-name>/` with content + `plugin.json`
3. Add entry to `.claude-plugin/marketplace.json`
4. Record provenance in `VENDORED.md`
5. Open MR using the "Add Vendored Plugin" MR template

## CODEOWNERS

All plugin directories under `/plugins/` require 1 Platform Team approval. `.claude-plugin/marketplace.json` requires 1 approval. Everything else defaults to 1 Platform Team approval via the catch-all rule.

## Team skill repos

Teams host their own skills in **separate private repos** under the `skillshub` group. They are **not** listed in this repo's `marketplace.json` — team repos run their own standalone marketplace (`.claude-plugin/marketplace.json` inside their own repo).

Developers add a team's marketplace directly:
```
/plugin marketplace add https://gitlab.example.com/platform-engineering/skillshub/<team-name>-skills.git
```

This keeps team plugin names and skill descriptions private — they never appear in this central repo.

Teams can MR here only to **add vendored upstream skills** to the Platform Team catalog (see "Adding a new upstream source" above). They cannot register their team repo as an entry in this `marketplace.json`.

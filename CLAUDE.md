# Claude Code — Contributor Context

This is the `skillshub/claude-marketplace` repo. It is the single URL tenants configure to get all Platform Team skills, plus a gateway for team-specific skill repos.

## Repo structure

```
.claude-plugin/marketplace.json   Central catalog (Platform Team only)
plugins/
  essentials/                     Curated starter pack — superpowers + feature-dev + pr-review
  platform-verified/              Full vendored catalog (154 skills, 58 agents, 72 commands)
ci/skill-scanner/                 LLM-as-judge safety scanner + GitLab CI component
VENDORED.md                       Upstream SHAs, licenses, what was included/excluded
CODEOWNERS                        Approval rules (GitLab Ultimate [Section][N] syntax)
```

## Two-plugin model

Tenants install one of two plugins:

- **`essentials`** — curated starter (TDD, debugging, planning, feature-dev, pr-review)
- **`platform-verified`** — everything: all 11 vendored sources merged into one plugin

Both live under `plugins/`. All upstream content is vendored (no runtime network calls).

## Vendored sources

All upstream skill repos are merged into `plugins/platform-verified/skills/` (and agents/, commands/, etc.). Individual source directories (`plugins/superpowers/`, etc.) do not exist — everything is consolidated. See `VENDORED.md` for upstream SHAs and what was included from each source.

## Airgap requirement

This repo must work fully offline once cloned. Do not add:
- Runtime `WebFetch` instructions in SKILL.md files that point to external URLs
- `live-sources.md` style dynamic URL registries
- Skills that `npx`-install packages at runtime (or document clearly that they require internet)

MCP SDK docs and other reference material should be vendored locally under `skills/<name>/reference/`.

## Skill safety scanner

The CI scanner (`ci/skill-scanner/`) evaluates SKILL.md files using an LLM-as-judge. It only scans changed SKILL.md files on MRs (via `SCANNER_FILES` env var). Full scan runs on push to main.

Requires `LITELLM_API_KEY`, `SCANNER_ENDPOINT`, and `SCANNER_API_KEY` as CI/CD variables.

## Adding a new upstream source

See README.md "For contributors" section for the full step-by-step. Short version:
1. Clone upstream into `/tmp/<source-name>`
2. Copy skill files into `plugins/platform-verified/` (and `plugins/essentials/` if broadly useful)
3. Record provenance in `VENDORED.md`
4. Bump versions in both plugin.json files
5. Open MR using the "Add Skill to Platform-Verified" template

## CODEOWNERS

`/plugins/essentials/` and `/plugins/platform-verified/` both require 1 Platform Team approval. `.claude-plugin/marketplace.json` requires 1 approval. Everything else defaults to 1 Platform Team approval via the catch-all rule.

## Team skill repos

Teams host their own skills in private GitLab repos under the `skillshub` group. They are NOT vendored here — tenants install them directly via `/plugin install <team-name>@claude-marketplace` after their repo is listed in `marketplace.json`. The Platform Team reviews structure (MR template), not skill content.

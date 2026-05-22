# Claude Code — Contributor Context

This is the `skillshub/claude-marketplace` repo. It is the Platform Team's curated skill catalog. It does **not** host team-specific skills — each team runs its own private marketplace.

## Repo structure

```
.claude-plugin/marketplace.json   Central catalog (Platform Team only) — name: platform-claude-marketplace
plugins/
  essentials/                     Curated starter pack — superpowers + feature-dev + pr-review
  superpowers/                    Vendored: obra/superpowers (14 skills)
  compound-engineering/           Vendored: EveryInc (38 skills + 50 agents)
  gstack/                         Vendored: garrytan/gstack (54 skills)
  ruflo/                          Vendored: ruvnet/ruflo (33 skills)
  getshitdone/                    Vendored: gsd-build (66 /gsd commands)
  anthropic-dev-skills/           Vendored: anthropics/skills (4 skills)
  obsidian/                       Vendored: kepano/obsidian-skills (5 skills)
  anthropic-feature-dev/          Vendored: anthropics/claude-plugins-official (feature-dev)
  anthropic-pr-review/            Vendored: anthropics/claude-plugins-official (pr-review)
  anthropic-hookify/              Vendored: anthropics/claude-plugins-official (hookify)
  frontend-design/                Vendored: anthropics/skills (frontend-design)
  appsec/                         Platform Team — 2 security scanning skills
  code-quality/                   Platform Team — 4 code/doc quality skills
ci/skill-scanner/                 LLM-as-judge safety scanner + GitLab CI component
VENDORED.md                       Upstream SHAs, licenses, what was included/excluded
CODEOWNERS                        Approval rules (GitLab Ultimate [Section][N] syntax)
```

## 14-plugin model

The marketplace (registered as `platform-claude-marketplace`) offers 14 installable plugins:

- **`essentials`** — curated starter (TDD, debugging, planning, feature-dev, pr-review). Install this first.
- **`appsec`** — Platform Team security scanning (Fortify SAST, DAST)
- **`code-quality`** — Platform Team code/doc quality tools
- **11 per-source vendored plugins** — `superpowers`, `compound-engineering`, `gstack`, `ruflo`, `getshitdone`, `anthropic-dev-skills`, `obsidian`, `anthropic-feature-dev`, `anthropic-pr-review`, `anthropic-hookify`, `frontend-design`

All upstream content is vendored (no runtime network calls).

## Vendored sources

Each upstream source has its own plugin directory under `plugins/<source-name>/`. See `VENDORED.md` for upstream SHAs and what was included from each source.

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
/plugin marketplace add https://gitlab.company.com/skillshub/<team-name>-skills.git
```

This keeps team plugin names and skill descriptions private — they never appear in this central repo.

Teams can MR here only to **add vendored upstream skills** to the Platform Team catalog (see "Adding a new upstream source" above). They cannot register their team repo as an entry in this `marketplace.json`.

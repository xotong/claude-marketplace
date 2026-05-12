---
name: xotong1-conventions
description: >
  Apply xotong1 internal engineering conventions when writing or reviewing code.
  Use this skill when the user asks to follow company standards, apply internal
  coding conventions, check code against xotong1 guidelines, or ensure consistency
  with how the team writes code. Also activate when the user says "follow our
  conventions", "use xotong1 style", or "make this match our standards".
  Do NOT activate for generic best-practices questions that have nothing to do
  with xotong1-specific conventions.
---

# xotong1 Engineering Conventions

When this skill is active, apply the following conventions consistently to all
code you write or review. If a convention conflicts with what the user explicitly
requests, flag the conflict and follow the user's instruction — these are defaults,
not overrides.

## Commit messages

Follow Conventional Commits (https://www.conventionalcommits.org):

```
<type>(<scope>): <subject>

[optional body]
[optional footer]
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`.
Subject line: imperative mood, ≤ 72 characters, no trailing period.
Body: wrap at 100 characters. Explain *why*, not *what*.

## Branch naming

```
<type>/<ticket-id>-<short-description>
```

Examples: `feat/PLAT-123-add-skill-scanner`, `fix/PLAT-456-jwt-expiry`.
Use kebab-case. No uppercase. Ticket ID is required for all non-trivial branches.

## Code style

**Python:**
- Formatter: `black` (line length 100)
- Linter: `ruff` — fix all auto-fixable issues before committing
- Type hints required on all public functions and class methods
- Prefer `pathlib.Path` over `os.path`
- Use `logging` module, not `print` statements, in library code

**TypeScript / JavaScript:**
- Formatter: `prettier` (default config)
- Linter: `eslint` with the internal config package `@xotong1/eslint-config`
- Prefer `const` over `let`; avoid `var`
- Explicit return types on exported functions

**General:**
- No commented-out code in committed files
- TODO comments must include a ticket ID: `# TODO(PLAT-789): remove after migration`
- Delete dead code rather than commenting it out

## Pull / Merge requests

- Title: same format as commit message subject line
- Description must include: Summary, Test plan, and any Breaking changes
- Link the ticket in the MR description
- Squash commits before merging to main (do not use merge commits on main)
- Self-review before requesting review: run tests, linter, and check diff yourself first

## Testing

- New features require tests. No exceptions.
- Test files live alongside the code they test: `foo.py` → `test_foo.py`
- Test names: `test_<what>_<given_condition>_<expected_result>`
- Aim for ≥ 80% branch coverage on new code; do not reduce existing coverage

## What NOT to do

- Do not commit secrets, tokens, or credentials — use environment variables
- Do not add `print()` debug statements to committed code
- Do not bypass lint/test CI with `--no-verify` or skip markers without a comment
- Do not merge your own MR without at least one review approval (unless emergency hotfix with post-merge review)

---
**To customise:** The Platform Team maintains this file. Open an MR against
`skillshub/claude-marketplace` to propose changes to these conventions.

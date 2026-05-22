---
name: lint-and-validate
description: >
  Run linters, formatters, and type checkers before every commit. Auto-fixes
  safe formatting issues, then reports remaining errors that must be resolved.
  Fast (seconds, not minutes) — designed as a mandatory pre-commit gate.
  Use when the user says: "lint", "format", "validate", "check code quality",
  "fix formatting", "run linter", "check before commit", "pre-commit check",
  "fix lint errors", "format code", "type check", "lint and validate",
  "/lint-and-validate". Also activate automatically before the user commits
  or creates a PR if lint has not been run in this session.
  Do NOT activate for security scanning — use appsec-scan for that.
---

# Lint and Validate

Run fast, auto-fixable quality checks before every commit. Fix what can be
fixed automatically, then report what requires manual attention.

## Step 1 — Detect Project Type

```bash
ls package.json requirements.txt pyproject.toml go.mod pom.xml Gemfile Cargo.toml \
   .eslintrc* .pylintrc .golangci* rubocop.yml 2>/dev/null
```

Identify: language(s), package manager, existing lint config files.

---

## Step 2 — Auto-fix Formatters (run first, always)

Apply formatters before running linters — this eliminates the most common lint failures instantly.

### Node.js / TypeScript
```bash
if [ -f package.json ]; then
  # Prettier (most common)
  if npx prettier --version 2>/dev/null | grep -q "[0-9]"; then
    npx prettier --write "**/*.{js,jsx,ts,tsx,json,css,scss,md,yaml,yml}" \
      --ignore-path .gitignore 2>/dev/null
    echo "Prettier: auto-formatted"
  fi
  # ESLint auto-fix
  npx eslint --fix "**/*.{js,jsx,ts,tsx}" 2>/dev/null || true
fi
```

### Python
```bash
if [ -f requirements.txt ] || [ -f pyproject.toml ] || find . -name "*.py" -maxdepth 3 | grep -q .; then
  # ruff (fast, fixes most issues)
  if which ruff 2>/dev/null; then
    ruff check --fix .
    ruff format .
    echo "ruff: auto-fixed and formatted"
  else
    # black + isort fallback
    which black 2>/dev/null && black . && echo "black: formatted" || true
    which isort 2>/dev/null && isort . && echo "isort: imports sorted" || true
    which autopep8 2>/dev/null && autopep8 --in-place --aggressive --recursive . || true
  fi
fi
```

### Go
```bash
if [ -f go.mod ]; then
  gofmt -w . && echo "gofmt: formatted" || true
  which goimports 2>/dev/null && goimports -w . && echo "goimports: imports fixed" || true
fi
```

### Ruby
```bash
if [ -f Gemfile ]; then
  which rubocop 2>/dev/null && rubocop --auto-correct-all 2>/dev/null || true
fi
```

### Rust
```bash
if [ -f Cargo.toml ]; then
  cargo fmt 2>/dev/null && echo "rustfmt: formatted" || true
fi
```

---

## Step 3 — Lint (report remaining errors after auto-fix)

### Node.js / TypeScript
```bash
if [ -f package.json ]; then
  echo "=== ESLint ==="
  npx eslint "**/*.{js,jsx,ts,tsx}" --format compact 2>/dev/null || true

  echo "=== TypeScript type check ==="
  if [ -f tsconfig.json ]; then
    npx tsc --noEmit 2>&1 | head -40 || true
  fi
fi
```

### Python
```bash
if which ruff 2>/dev/null; then
  echo "=== ruff ==="
  ruff check . 2>/dev/null || true
else
  echo "=== flake8 ==="
  which flake8 2>/dev/null && flake8 . --max-line-length 120 \
    --exclude=.git,__pycache__,venv,.venv,migrations 2>/dev/null || true

  echo "=== pylint ==="
  which pylint 2>/dev/null && \
    find . -name "*.py" -not -path "*/venv/*" -not -path "*/.venv/*" | \
    head -20 | xargs pylint --disable=C0114,C0115,C0116 2>/dev/null || true
fi

echo "=== mypy (type check) ==="
which mypy 2>/dev/null && mypy . --ignore-missing-imports 2>/dev/null | head -30 || true
```

### Go
```bash
if [ -f go.mod ]; then
  echo "=== go vet ==="
  go vet ./... 2>&1 || true

  echo "=== golangci-lint ==="
  which golangci-lint 2>/dev/null && golangci-lint run --timeout=60s 2>/dev/null || \
    echo "golangci-lint not installed — install from https://golangci-lint.run"

  echo "=== go build ==="
  go build ./... 2>&1 | head -20 || true
fi
```

### Ruby
```bash
[ -f Gemfile ] && which rubocop 2>/dev/null && rubocop --format progress 2>/dev/null || true
```

### Rust
```bash
[ -f Cargo.toml ] && cargo clippy -- -D warnings 2>/dev/null || true
```

---

## Step 4 — Check Common Config Issues

```bash
echo "=== Config checks ==="

# .env files tracked by git
git ls-files 2>/dev/null | grep -E '^\.env$|^\.env\.' | \
  grep -v '\.env\.example\|\.env\.sample\|\.env\.template' && \
  echo "ERROR: .env file committed — add to .gitignore and remove from git tracking" || true

# Large files that shouldn't be committed
git diff --cached --name-only 2>/dev/null | \
  xargs -I{} find {} -maxdepth 0 -size +5M 2>/dev/null | \
  head -5 | while read f; do echo "WARNING: Large file staged: $f"; done

# Missing .gitignore
[ ! -f .gitignore ] && echo "WARNING: No .gitignore found" || true

# package-lock.json / yarn.lock inconsistency
[ -f package.json ] && [ -f yarn.lock ] && [ -f package-lock.json ] && \
  echo "WARNING: Both yarn.lock and package-lock.json present — pick one" || true
```

---

## Step 5 — Report and Block

After all checks:

1. **If any errors remain** after auto-fix: list them clearly with file:line references. Do not proceed with the commit. Ask the user to fix each one.

2. **Format of error report:**
   ```
   ERRORS (must fix before commit):
   - [eslint] src/api/users.ts:42 — 'password' used in string concatenation (no-string-concat-sql)
   - [tsc] src/types/user.ts:17 — Property 'email' does not exist on type 'User'

   WARNINGS (should fix, won't block):
   - [eslint] src/utils/helper.ts:8 — console.log statement (no-console)
   ```

3. **If clean:** confirm "Lint and validate passed — safe to commit."

## What NOT to do

- Do not run security scans here — use appsec-scan for that.
- Do not skip the auto-fix step — always run formatters first.
- Do not report warnings as errors or block commits on warnings alone.
- Do not modify test files' content, only their formatting.

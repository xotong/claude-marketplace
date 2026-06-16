# AppSec Scan Update Guide

`appsec-scan` no longer vendors one shell runner per scanner as the primary
source of truth. The skill resolves current Chronicle GitLab component templates
at scan time, then uses `scripts/appsec_harness.py` to render local Docker runs.

## What To Update

### Chronicle changes a component script

Usually no marketplace change is required. Tenants pick up the change the next
time the helper fetches the template from Chronicle.

If the component output format changes, update:

- `scripts/appsec_harness.py` parser logic
- `tests/test_appsec_harness.py` fixtures
- `references/chronicle-components.yaml` artifact or input hints if needed

### Chronicle adds a scanner component

Add one entry to `references/chronicle-components.yaml`:

- `template_path`
- `scanner`
- `kind`
- detector rules
- input defaults
- required env vars

Add parser support only if the scanner emits a new report format.

### Chronicle retires a scanner

Remove or disable the registry entry. Do not leave stale default-enabled
components in the registry.

### A scanner needs different local behavior

Prefer registry metadata first. Change Python only when behavior cannot be
expressed as template path, inputs, detection rules, required env vars, or image
override.

## Local Validation

Run without Docker or credentials:

```bash
python3 -m py_compile plugins/appsec/skills/appsec-scan/scripts/appsec_harness.py
python3 -m pytest plugins/appsec/skills/appsec-scan/tests
```

Run resolution against a local Chronicle checkout:

```bash
export APPSEC_CHRONICLE_LOCAL_DIR=/path/to/chronicle
python3 plugins/appsec/skills/appsec-scan/scripts/appsec_harness.py \
  --project-dir /path/to/project \
  run --dry-run --include-unconfigured
```

Run remote resolution with a pinned Chronicle commit:

```bash
export APPSEC_COMPONENT_REF=<chronicle-commit-sha>
export APPSEC_COMPONENT_RAW_BASE="https://gitlab.example.com/group/chronicle/-/raw/{ref}"
export APPSEC_ALLOWED_COMPONENT_HOSTS=gitlab.example.com
python3 plugins/appsec/skills/appsec-scan/scripts/appsec_harness.py \
  --project-dir /path/to/project \
  resolve
```

Run a real local scan only when scanner images, Docker, network, and credentials
are available:

```bash
python3 plugins/appsec/skills/appsec-scan/scripts/appsec_harness.py \
  --project-dir /path/to/project \
  run --gate ci
```

Production validation should check these failure modes:

- missing required scanner environment variables create `scan-coverage.json` and
  high-severity configuration findings
- malformed scanner reports fail the CI gate
- remote templates without a pinned commit SHA are refused unless explicitly
  allowed for development
- raw GitLab URL mode requires `{ref}` in `APPSEC_COMPONENT_RAW_BASE`
- stale cache fallback requires `--allow-stale-cache`
- stale cache files require matching metadata and SHA-256
- real scanner runs require digest-pinned images unless mutable image risk is
  explicitly accepted
- scanner reports must be declared as artifacts and collected under
  `.appsec-results/reports/<component>/`
- `prepare-branch` refuses a dirty worktree unless `--allow-dirty` is supplied

## Legacy Runners

The `scanners/` shell scripts are retained for compatibility while teams migrate
to the Chronicle resolver. Do not add new scanner logic there unless a tenant
still depends on the legacy path.

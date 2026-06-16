# Chronicle Harness Reference

Use this reference when `appsec-scan` needs implementation detail beyond the
quick workflow in `SKILL.md`.

## Resolution Order

The harness resolves current Chronicle component templates in this order:

1. `APPSEC_CHRONICLE_LOCAL_DIR`: read templates from a checked-out Chronicle repo.
2. `APPSEC_COMPONENT_RAW_BASE`: fetch `/<component>/templates/<component>.yml`
   style paths from a raw base URL.
3. `APPSEC_GITLAB_URL` plus `APPSEC_GITLAB_PROJECT`: call GitLab's repository
   files raw endpoint. `APPSEC_GITLAB_TOKEN` is optional for public/internal
   projects and required for private projects.
4. `${HOME}/.cache/claude-appsec/component-cache`: use cached templates only
   with `--allow-stale-cache` after live resolution fails, and print a
   stale-cache warning.

Set `APPSEC_COMPONENT_REF` to a Chronicle commit SHA for tenant use. Mutable refs
such as `main` require `APPSEC_ALLOW_UNPINNED_COMPONENTS=true` and should be used
only in controlled development. `APPSEC_COMPONENT_RAW_BASE` must include `{ref}`
so the pinned commit is part of the final URL. Set
`APPSEC_ALLOWED_COMPONENT_HOSTS` to a comma-separated allowlist for remote
template hosts.

## Local Execution Model

The harness renders the component inputs from `references/chronicle-components.yaml`,
substitutes GitLab `$[[ inputs.* ]]` expressions, drops SRM upload helper jobs,
and runs the remaining scanner job script inside Docker with the component image.
Generated runner exports are shell-quoted, Docker entrypoints are reset, and
secret variables are passed with `--env KEY` rather than `KEY=value` in Docker
argv. Real scanner runs use a disposable copy under `.appsec-results/workspaces`
so scanner containers cannot modify the tenant source checkout.

Scanner images must be pinned with `@sha256:` for real runs unless
`APPSEC_ALLOW_MUTABLE_IMAGES=true` is set after accepting image drift risk. Use
`APPSEC_ALLOWED_IMAGE_REGISTRIES` to restrict scanner images to approved
registries.

The harness intentionally excludes Fortify DAST in v1. DAST requires reachable
environments, scan settings, auth macros, and long-running API polling. Use
`appsec-dast-sim` for WSTG design-time coverage and run real DAST in CI.

## Outputs

All outputs live under `.appsec-results/`:

- `resolved-jobs.json`: resolved local job model.
- `scan-coverage.json`: scanners resolved and scanners skipped because required
  configuration was missing.
- `<component>.sh`: generated local runner scripts.
- `<component>.log`: scanner logs.
- `workspaces/<component>/`: disposable scanner workspace copy.
- `reports/<component>/`: collected parseable scanner artifacts declared by the
  Chronicle component.
- `findings.normalized.json`: merged finding model.
- `findings.triaged.json`: normalized findings with verification status.

## Verification Status

Use these statuses consistently:

- `confirmed_true_positive`: evidence points to reachable vulnerable code or a
  dependency/image issue that the scanner can prove.
- `likely_false_positive`: generated/vendor/test paths, explicit suppression,
  or missing reachability evidence makes the finding unlikely to affect shipped
  code.
- `not_fixable_locally`: the issue needs image rebuilds, base-image/vendor
  updates outside the repo, Fortify/Prisma/SRM configuration, or infrastructure
  changes.
- `needs_human_review`: evidence is insufficient for a confident call.

Never silently suppress false positives. Present them to the user with evidence.
High and critical likely false positives still fail the CI gate until a user
accepts the risk or the issue is fixed.

## Remediation Loop

Default remediation is local-only:

1. Create `appsec/remediate/<base>-<timestamp>` if not already on an appsec
   remediation branch. The worktree must be clean unless `--allow-dirty` is used
   intentionally.
2. Run `appsec_harness.py run --gate ci`.
3. Normalize and triage results.
4. Fix only `confirmed_true_positive` findings that are locally fixable.
5. Re-run until the CI gate is clean, no viable fixes remain, or five iterations
   have completed.

Do not push or open an MR unless the user explicitly asks.

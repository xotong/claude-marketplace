# Changelog

All notable changes to appsec-scan are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added

- **The Fortify JDK variant is now detected from the codebase — no configuration.**
  `scripts/detect-java-release.sh` reads the compile target out of every `pom.xml`
  (`maven.compiler.release|source|target`, `java.version`, the compiler plugin's
  `<release>/<source>/<target>`) and every `*.gradle[.kts]`
  (`JavaLanguageVersion.of(N)`, `jvmToolchain(N)`, `source|targetCompatibility` in all
  of its spellings) — every, not just `build.gradle`, so a `buildSrc` convention
  plugin counts, and a version referenced by name is resolved from
  `gradle.properties` — takes the **highest** release found, and
  `scripts/select-jdk-variant.sh` maps it to the smallest variant the component
  offers that can still compile it. The offered set is read from the component as
  resolved that run, so a platform team publishing `jdk25-review` — or retiring
  `jdk17-review` — reaches every developer with no MR against this repo, the same
  way `version: ~latest` already rolls out a component version;
  `scanners/fortify-sast.contract` is the offline fallback and `check-drift` still
  reports the change. When nothing offered is new enough the highest runs and the
  scan warns. Both halves of that follow from one property — a JDK compiles its own
  release and every earlier one but never a later one — so the *highest* release
  declared in the repository decides the *smallest* usable image. Generated copies
  under `target/` and `build/` are pruned so a stale artifact cannot outvote the
  source. Same shape as
  `FORTIFY_LANGUAGE`: automatic, with `FORTIFY_VARIANT` as the environment override.
  A detected variant outranks the variant in `image:` — it is evidence from the
  repository rather than a line typed once — but it stays a preference: if the registry
  does not carry it, the scan warns and runs the component's default rather than
  failing. `.tool-versions`, `.sdkmanrc` and `.java-version` are deliberately not read;
  they pin a developer's toolchain, not the build's target

### Fixed

- **A configured JDK variant is no longer silently replaced by the component's default.**
  A Fortify tag carries the JDK the target compiles with (`25.2.0-jdk17-review` vs
  `-jdk21-review`), and `follow-component` adopted the template's tag whole — so an
  admin who pinned `…:25.2.0-jdk21-review` for a Java 21 project got the component's
  JDK 17 analyzer, with nothing said. `resolve-image.sh` now applies the existing rule
  one field further right: the component owns the **version**, the admin owns the
  registry, path **and variant**. `…:25.2.0-jdk21-review` against a template declaring
  `25.2.1-jdk17-review` now resolves to `…:25.2.1-jdk21-review`, and the substitution is
  announced on stderr. Tags without a version-shaped head (`latest`) or without a
  suffix (`container-scanning:8.6.31`) are unaffected

## [3.3.0] — 2026-08-08

### Changed — BREAKING

- **`image:` and `runner:` are now optional, and the component decides the image.**
  `settings.image_policy: follow-component` (the new default) resolves the analyzer
  image from the component template at the resolved tag via `scripts/resolve-image.sh`:
  with no `image:` the template's ref is used whole; with one, `image:` supplies the
  registry and path and the template supplies the tag, so a component bump reaches an
  airgapped estate without editing config and without ever pulling from a public
  registry. `image_policy: pinned` keeps the old verbatim behaviour. `runner:` defaults
  to the category's shipped runner. Both shipped profiles now declare only
  `component` + `version` + `enabled`
- Migration: nothing breaks for a config that still declares `image:` — under
  `follow-component` it becomes the registry/path and the fallback when a tag is not
  mirrored. To keep byte-identical refs, set `settings.image_policy: pinned`. **Deriving
  the image makes the vendored snapshots load-bearing:** snapshots taken from gitlab.com
  name gitlab.com's registry, so re-vendor from your own instance before rollout
  (`scripts/revendor.sh`, MIGRATION.md "Re-vendor")
- The candidate image is pulled once as an availability check, which also warms the
  cache the scan is about to use. A mirror that lacks the tag falls back to `image:`
  with the exact ref to mirror; with nothing to fall back to, the scan **stops** — a
  scanner whose image cannot be determined must never be silently skipped
- `ENABLED_COMPONENTS` tuples gained a fifth field: `component|version|runner|image|category`
- The fix loop's progress guard now compares `ACTIONABLE C+H`, not `TOTAL C+H`

### Added

- `catalog.sh template-image <component> <cache>` — prints the component's effective job
  image, expanding `$[[ inputs.x ]]`, `$VAR` and `${VAR}` against the template's own
  `spec.inputs` defaults and `variables:` blocks (dependency-scanning builds its ref that
  way). Prints nothing rather than guessing when a variable is undeclared
- **Offline dependency vulnerability matching** (`scanners/sbom-vuln-scan.sh`). Locally,
  Dependency Scanning emits only an SBOM — GitLab matches it server-side behind an API
  that accepts nothing but a real `CI_JOB_TOKEN`, so no local runner (this skill, `glci`,
  `gitlab-ci-local`, `gitlab-runner exec`) can reproduce those results. An SBOM alone
  normalizes to zero findings and reads as "scanned, clean", so the SBOM is now matched
  against the advisory DB baked into the container-scanning image using its bundled
  Trivy. **Those findings are Trivy's, not GitLab's** — a different advisory source that
  will not match the post-push Vulnerability Report in content or count. Documented
  everywhere it surfaces as a pre-push triage signal, never as a CI prediction. If the
  pass cannot run, dependency scanning is recorded as a coverage skip, not as clean
- **Remediation reachability probe before the fix loop** (`scripts/check-remediation.py`,
  `resolve-package.sh`, `settings.package_registries`). Each suggested upgrade is checked
  against the internal mirror; `absent` ⇒ `remediation_status: blocked_registry_gap`,
  which the fix loop skips and TRIAGE.md §3b batches into one mirroring request. `unknown`
  (unreachable, auth failure, 5xx, no template) changes nothing — a registry we could not
  reach is not evidence a package is missing
- **Base-image availability probe** (`scripts/resolve-base-image.sh`,
  `settings.container_registry.base_repo`). `container-target.sh` now parses the
  Dockerfile's `FROM` lines into `base-images.json` — resolving `ARG` defaults, build
  stages and `scratch` — and each base image is probed. `absent` routes container findings
  to `blocked_registry_gap` with the image to mirror, instead of the generic "no fixed
  version" dead end
- `settings.container_registry.hardened_repo` — **suggestion only**. Verdicts are filed
  under keys no status decision reads, and the fix loop must never apply one: a hardened
  image is a different image (libc, no shell, non-root UID), so a human decides
- Airgap plumbing in `settings:` — `ca_bundle` (mounted read-only, exported inside each
  scanner as `ADDITIONAL_CA_CERT_BUNDLE`), `pip_index_url` and `maven_settings`, because
  the dependency analyzer's own defaults (public PyPI, `./settings.xml`) hang on an
  airgapped host and report a broken SBOM rather than a resolution failure
- `CS_DOCKERFILE_PATH` is exported in registry mode when a Dockerfile is present. The
  component declares that input; nothing set it locally, so GTCS's own base-image
  remediation never ran
- `ACTIONABLE C+H` in the summary — critical+high minus what nothing local can act on
- Fortify **go** support: the `go)` arm mirrors the component's go job (`go mod download`
  then `sourceanalyzer -debug-verbose`), `run-scan.sh` detects `go.mod`, and
  `FORTIFY_LANGUAGE=go` is documented in SKILL.md's description and prerequisites — the
  model could not select a language SKILL.md never named
- SAST findings now carry `evidence.solution`, joined from the FVDL `<Description
  classID>` blocks. Fortify keeps its guidance there, not on the vulnerability elements,
  so every SAST finding previously reached the developer with no remediation text
- Step 0 scan-scope routing in SKILL.md: keyword → `SCAN_SCOPE`, an `AskUserQuestion`
  picker labelled in plain language when the request is ambiguous, and `--only` wired
  through. A scoped run still expects full coverage, so it can never read as an all-clear
- `ci/check-appsec-drift.py` + a `check-appsec-drift` CI job: compares every runner
  against the vendored snapshots fully offline (no token, no network) and **blocks on
  `CONTRACT-DRIFT`**. Image and 90-day staleness DRIFT stay advisory
- Trivy ecosystem mapping (`node-pkg` → npm, `jar` → maven, …) so a probe knows which
  registry to ask

### Fixed

- **`run-scan.sh` resolved images from a hardcoded component table.** An admin who
  repointed `component:` still had the image derived from the OLD component, and silently:
  the vendored snapshot for the hardcoded path yields
  `registry.gitlab.com/security-products/container-scanning:8.6.31`, which pulls fine on
  an internet-connected host — so the scan ran the PUBLIC analyzer instead of the
  configured internal mirror with nothing saying so. Component paths now come from
  `ENABLED_COMPONENTS`
- **`--dry-run` was dead on both shipped profiles.** With no `image:` it tried to pull the
  candidate for real, which a dry run must not do; resolution now runs in `no-pull` mode
- **Two silent false-PASSED paths in `load-prefs.sh`.** A comment on the same line as a
  key (`enabled: true  # on`) and a CRLF line ending both made `enabled: true` parse as
  something else, dropping the scanner from the run with no warning — the same false
  all-clear class as 3.2.0's four
- **Phantom HIGH findings from our own bookkeeping.** `registry-availability.json` and
  `base-images.json` live in `.appsec-results/`, so `normalize.py` parsed them as scanner
  reports, failed, and raised an "unsupported report schema" HIGH that failed the gate on
  its own
- Redaction mangled `evidence.manifest` and `evidence.package`, destroying the ecosystem
  signal the mirror probe needs — an unavailable upgrade could never be marked blocked.
  Those two are tool-derived, never scanner-captured, and now join `why` as protected
- Container findings could never reach the base-image gap: `blocked_external_dependency`
  swallowed every one of them first, because container findings routinely arrive with no
  `fixed_version`. The more specific — and only actionable — verdict now wins
- Trivy reports written for a dependency SBOM were categorised as container scanning and
  given an `image` location; they now take their category from the report name and a
  `package` location
- `container-target.sh` only looked for a Dockerfile when `CS_IMAGE` was unset, so
  registry-mode runs never produced `base-images.json`
- `resolve-package.sh`: expanding a possibly-empty array under `set -u` aborted on bash
  3.2 (macOS), and Go module paths were not `!`-escaped for GOPROXY, so every uppercase
  module probed as absent
- The CI drift gate silently checked **zero** components once `runner:` became optional:
  it skipped every category whose config omitted one, so a green pipeline meant nothing.
  It now applies the same default-runner mapping `load-prefs.sh` uses, with a regression
  test that parses that Bash function and compares the two maps

### Documentation

- Every document reconciled against actual behaviour. `image:` now has exactly one
  description (PREFERENCES.md "Per-category settings"); SKILL.md, PREFERENCES.md and
  ARCHITECTURE.md no longer claim the pinned image runs and the catalog is advisory
- MIGRATION.md step 1 derives the refs to mirror from `catalog.sh template-image` instead
  of from a profile that no longer declares any; the `mode: online` precondition removed
  (that setting went in 3.2.0); step 4 gained the airgap and probe settings
- UPDATE-GUIDE.md: Scenario 3 rewritten (a retag usually needs no config change), the
  `go` worked example marked done, budget numbers corrected to 330 lines / 17,400
  characters, and two commands that fail as written fixed (`RUN_GITLAB_SAST_SMOKE`, and
  `sh /runner.sh` for a `#!/usr/bin/env sh` runner)
- `CI_PROJECT_URL` dropped from SKILL.md's prerequisites — nothing reads it
- Recorded in ARCHITECTURE.md: the four catalogue components this skill does not cover,
  and why `dast` and `api-security` are **declined** rather than pending (both need a
  deployed, running, authenticated target that a working-tree scan cannot provide;
  `appsec-dast-sim` covers the design-time intent)

## [3.2.0] — 2026-07-25

### Added
- `catalog.sh contract` + `scanners/<runner>.contract`: the component's declared inputs, permitted `options:` and report artifacts, extracted from `template.yml` as sorted flat text (no jq/python dependency). `check-drift` diffs the live component against it and emits `CONTRACT-DRIFT:` — this is what catches a new input such as fortify-sast's `go` language option
- `scripts/resolve-components.sh`: Step 2.5 as a script. The SKILL.md loop it replaces relied on the shell word-splitting an unquoted variable, which bash does and zsh does not — on a zsh host it silently resolved 1 of 4 components and emitted a bogus DRIFT line from the unparsed remainder
- `NEEDS-MAPPING:` escalation prefix, emitted when a component declares a capability no runner implements (currently fortify-sast `go`)
- `coverage_complete` in `scan-coverage.json`, separate from `gate_passed`, because `ci_gate.fail_on: none` is report-only and always passes
- Actionable `evidence.why` on every coverage finding, naming the fix (registry login, add a Dockerfile, add a lock file, run from inside a Git worktree)
- `.appsec-results/.gitignore` containing `*`, so the results directory self-excludes without editing the project's `.gitignore`

### Fixed
- **False all-clear (four distinct paths).** Expected coverage is now read from `scanner-preferences.yaml`, independent of the invocation. Previously it came from each scanner's success path, from `--only`, and from the `RUN_*` environment, so a category could be absent from *both* `scanners_run` and `missing_report`. A Go repo with no Dockerfile reported `PASSED`/exit 0 with SAST and container scanning never run; a `--only` rescan overwrote the coverage record clean *every fix-loop iteration*; one stale `export RUN_SECRET_DETECTION=true` suppressed the self-load and dropped three enabled categories with no warning at all
- Incomplete coverage now fails the gate at every threshold except `none`
- SAST image path: the `fortify-sast` project has no container registry; images live in the catalogue's `docker-images` project. The configured path did not exist and could never have pulled
- Image drift detection never fired: it looked for a `spec.inputs.image_tag.default` that only the synthetic self-test fixture had. Now derives the effective job image, resolving `$[[ inputs.X ]]` against declared defaults
- Raw scanner reports (including `gl-secret-detection-report.json`, which carries `raw_source_code_extract`) were left in the project root, one `git add -A` from being committed. Runners now move rather than copy
- `run-scan.sh` standalone exited 2: it self-loaded preferences but `load-prefs.sh` never emits `RUNTIME`. It now self-detects the container runtime
- `preflight.sh` passed with a dead Docker daemon — `detect-runtime.sh` only checked binary presence. Adds `--require-daemon` with a bounded probe (macOS has no `timeout(1)`)
- `fix-branch.sh --check-progress` silently accepted non-integer arguments, writing invalid JSON into the loop state and exiting 0 as if progress had been made
- SKILL.md Step 1 derived `SKILL_DIR` from `${BASH_SOURCE[0]}`, which resolves to the agent's shell (`/bin`), and assumed one persistent shell across steps

- `scripts/revendor.sh`: one command to refresh the vendored snapshots and regenerate the contracts from a live instance. It **refuses** to vendor any component that resolved `[offline-fallback]`, which would copy a snapshot onto itself and make a stale component look freshly confirmed
- `APPSEC_CATALOG_TIMEOUT` / `APPSEC_CATALOG_RETRIES`: catalog reads now retry transient failures (default 2) and use a 15s timeout. A cold TLS handshake or a brief 5xx previously degraded one component straight to `[offline-fallback]`, which reads as an auth problem when it was a hiccup. 401/404 still fail fast

### Removed
- `settings.catalog.mode`. Components are always resolved live against the active profile's `gitlab_instance`, with automatic fallback to the vendored snapshots when that fetch fails. The forced-offline setting provided nothing the design did not already give — exact `version:` pins give reproducibility, the fallback gives airgap resilience — while silently disabling image and contract drift detection, since `scanners/*.contract` are generated from the very snapshots the check would compare against. It also risked serving gitlab.com-vendored snapshots as though they were an internal instance's components. `catalog.sh resolve --offline` remains for tests and one-off manual use
- Consequently, preflight now requires a named `auth_token_env` var whenever one is named; there is no mode in which the requirement is skipped

### Changed
- `auth_token_env` is settable **per profile**, next to `gitlab_instance`, because it is a property of the instance. A profile value (including an explicit `""`) overrides `settings.catalog.auth_token_env`. This lets the gitlab.com `catalog` profile require a PAT while the internal `company` profile reads anonymously — previously impossible, since both were global
- `company` profile ships `auth_token_env: ""` for an internal instance serving the catalogue anonymously
- `ENABLED_COMPONENTS` is now a `component|version|runner|image` tuple; the image is what `check-drift` compares against
- TRIAGE.md restructured into four sections — fixed on this branch, must-fix (not dismissible), coverage gaps (not dismissible), then GitLab dismissals. Coverage gaps and unfixed true positives have no GitLab vulnerability to dismiss, so forcing them into one of the five dismissal reasons was misleading
- Vendored snapshots refreshed: dependency-scanning and container-scanning 1.0.0 → 1.1.0; fortify-sast@25.2.0 re-fetched after the registry move
- SKILL.md budget raised to 275 lines / 13,800 chars to fit the escalation-prefix table

## [3.1.0] — 2026-07-16

### Added
- `scripts/run-scan.sh` orchestrator: replaces ~500 lines of scanner code that were in SKILL.md Steps 3–5
- `scripts/normalize.py`: stdlib-python pipeline producing `findings.triaged.json` (per-finding `verification_status`: confirmed_true_positive | likely_false_positive | not_fixable_locally | needs_human_review), `findings.normalized.json`, `scan-coverage.json`; coverage findings created for any scanner that produces no report (HAS_MISSING_REPORT semantics — not an all-clear)
- `scripts/resolve-python.sh`: python3 provisioner mirroring `resolve-jq.sh` (host python3 preferred → `settings.python.install_url` download → legacy jq-count degrade with UNKNOWN statuses)
- `scripts/fix-branch.sh`: fix-loop guard (`--init` creates branch `appsec/fix-<YYYYMMDD>-<shortsha>` + loop-state; `--check-progress <prev> <curr>` exits 1 on iteration > 5 or no-progress)
- `settings.python.install_url` in scanner-preferences.yaml: mirrors `settings.jq.install_url`; admin points at platform-hosted portable python3 tarballs
- `settings.ci_gate.fail_on` in scanner-preferences.yaml: `critical` | `high` | `medium` | `none`
- `CHANGELOG.md` (this file) and `MIGRATION.md` (internet → airgapped platform runbook)
- SKILL.md reduced to ~258 lines (CI hard limit: 260 lines / 13,000 chars)
- Salvaged from unmerged chronicle harness commit 48c19ba (tagged `archive/appsec-chronicle`): single-entrypoint harness concept; parsers and triage logic absorbed into `normalize.py`; gate logic absorbed into `run-scan.sh`

### Cross-platform
- GNU/BSD/MSYS `date` portability fix (no `-d`, uses `+%s` arithmetic)
- `curl` temp-file (no process substitution, avoids WSL2/Git-Bash pipe hangs)
- `realpath` replaced with `cd`/`pwd` for POSIX portability
- `.gitattributes` enforcing LF line endings for all shell scripts
- `catalog.sh`: offline-mode network enforcement (resolve skips network when `CATALOG_MODE=offline`)
- Watchdog pipe-hang fix (background scanner cleanup)
- Zero-scanner false-PASSED fix: `run-scan.sh` self-loads prefs when `RUN_*` flags absent
- Normalize rglob hygiene (no accidental `.appsec-results/` recursion)
- Preflight WSL2 advisory for native-Windows users
- Platform support matrix added to README.md, PREFERENCES.md, MIGRATION.md (macOS/Linux/WSL2 fully supported; native Windows via Git Bash + Docker Desktop best-effort; native PowerShell not supported)

### Changed
- SKILL.md Steps 3–5 replaced by single `bash "$SCRIPTS_DIR/run-scan.sh"` invocation; Steps 1–2.5 byte-identical to v3.0.0

### Removed
- Scanner orchestration bash from SKILL.md Steps 3–5 (~500 lines)

> **Production-readiness gate — small-model (gemma:9b-class) executability.**
> Weighted rubric: executability 30%, correctness 25%, safety 20%, docs 15%, airgap 10%.
> Gate = min of two independent final judges ≥ 9.0. **Met: 9.1.**
>
> | Round | Fable | gpt-5.6-sol | Empirical (Haiku) | Key defects found |
> |---|---|---|---|---|
> | 1 | — | — | exec 5 | missing `export` broke Step 3 in a child shell; fix-loop off-by-one |
> | 2 | — | 3.8 | exec 6 | dry-run credential leak; empty-report false all-clear; severity→LOW; redaction gaps |
> | 3 (blockers) | 7.5 | 6.2 | — | watchdog pipe-hang (1 h stdout block); zero-scanner false PASSED; offline still hit network |
> | 4 (final) | **9.1** | 7.3 → **9.2** | — | incomplete false all-clear (empty-image / `--only` disabled); watchdog TERM-only; `rule_id` redaction |
>
> Final: **Fable 9.1** (exec 9 / corr 9 / safety 9 / docs 9 / airgap 10) · **gpt-5.6-sol 9.2**
> (exec 9.1 / corr 9.3 / safety 9.3 / docs 9.0 / airgap 9.2). Every judge finding was
> reproduced first-hand before fixing; the adversarial deep-code judge repeatedly caught
> real safety gaps (false all-clears, credential leaks) that happy-path review missed.
>
> Documented non-blocking limitations: parallel-scanner timeout kills the scanner PID but
> not grandchildren without `setsid`; bare interactive paste of Step 1 can mis-resolve
> `SKILL_DIR` (the model-harness path and `run-scan.sh` self-location are unaffected).

---

## [3.0.0] — 2026-07-15

### Added
- 4 private-catalogue CI/CD components (Fortify SCA, Dependency Scanning, Secret Detection, Container Scanning) from `lobster-thermidor/devops/ci-catalogue`
- Per-component version pinning (`~latest` or exact tag) with ADVISORY on catalog drift
- `AGENTS.md` vendored per component tag (agent-oriented usage reference)
- `catalog` and `company` profiles in `scanner-preferences.yaml`
- Architecture README and poster (`docs/architecture.drawio` + `docs/architecture.png`)

### Removed
- Semgrep, DAST (delegated to `appsec-dast-sim`), and 9 legacy scanners
- All `semgrep`/`dast`/`parasoft`/`pylint`/`eslint`/`scantist` references

---

## [2.0.0] — 2026-07-05

### Added
- Catalog-driven profiles via `scanner-preferences.yaml` + `load-prefs.sh`
- `catalog.sh` with live resolve + offline fallback + drift advisories
- Airgap hardening (`settings.airgap`; `company` profile for internal mirror)
- docker|podman auto-detection (`detect-runtime.sh`)
- Hermetic pytest suite + CI

---

> **[1.1.0-chronicle] — 2026-06-17** *(unmerged experiment; tagged `archive/appsec-chronicle`, commit 48c19ba)*
> Single-entrypoint harness replacing the multi-step SKILL.md model; shipped parsers, triage engine, and gate logic. Not merged: the harness introduced an external runtime dependency. Core logic salvaged into 3.1.0 `normalize.py` and `run-scan.sh`.

---

## [1.0.0] — 2026-05-22

### Added
- Initial CI mirror: Fortify SCA (python/js), Parasoft, Pylint, ESLint, Scantist, Trivy
- Env-var image interface (`FORTIFY_SAST_IMAGE`, `SECRET_DETECTION_IMAGE`, …)

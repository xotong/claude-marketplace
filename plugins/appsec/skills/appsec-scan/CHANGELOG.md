# Changelog

All notable changes to appsec-scan are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

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

### Changed
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

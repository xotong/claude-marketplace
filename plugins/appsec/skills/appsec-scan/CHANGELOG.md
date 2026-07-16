# Changelog

All notable changes to appsec-scan are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [3.1.0] — 2026-07-16

### Added
- `scripts/run-scan.sh` orchestrator: replaces ~500 lines of scanner code that were in SKILL.md Steps 3–5
- `scripts/normalize.py`: stdlib-python pipeline producing `findings.triaged.json` (per-finding `verification_status`: confirmed_true_positive | likely_false_positive | not_fixable_locally | needs_human_review), `findings.normalized.json`, `scan-coverage.json`; coverage findings created for any scanner that produces no report (HAS_MISSING_REPORT semantics — not an all-clear)
- `scripts/resolve-python.sh`: python3 provisioner mirroring `resolve-jq.sh` (host python3 preferred → `settings.python.install_url` download → legacy jq-count degrade with UNKNOWN statuses)
- `scripts/fix-branch.sh`: fix-loop guard (`--init` creates branch `appsec/fix-<YYYYMMDD>-<shortsha>` + loop-state; `--check-progress <prev> <curr>` exits 1 on iteration > 5 or no-progress)
- `settings.python.install_url` in scanner-preferences.yaml: mirrors `settings.jq.install_url`; admin points at platform-hosted portable python3 tarballs
- `settings.ci_gate.fail_on` in scanner-preferences.yaml: `critical` | `high` | `medium` | `none`
- `CHANGELOG.md` (this file) and `MIGRATION.md` (internet → airgapped platform runbook)
- SKILL.md ≤250 lines enforced by CI (hard limit: 260 lines / 13 000 chars)
- Salvaged from unmerged chronicle harness commit 48c19ba (tagged `archive/appsec-chronicle`): single-entrypoint harness concept; parsers and triage logic absorbed into `normalize.py`; gate logic absorbed into `run-scan.sh`

### Changed
- SKILL.md Steps 3–5 replaced by single `bash "$SCRIPTS_DIR/run-scan.sh"` invocation; Steps 1–2.5 byte-identical to v3.0.0

### Removed
- Scanner orchestration bash from SKILL.md Steps 3–5 (~500 lines)

<!-- SCORES -->
> **Production-readiness gate (4-judge panel):** scores recorded here after the loop.

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

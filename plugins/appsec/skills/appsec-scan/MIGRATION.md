# Migration Guide — Internet → Airgapped Platform

Use this runbook when moving from the default `catalog` profile (which resolves live against gitlab.com) to the `company` profile (internal GitLab + internal JFrog registry). Cross-references: `config/PREFERENCES.md` (schema), `UPDATE-GUIDE.md` (snapshot refresh), `README.md` (architecture, platform support matrix).

> **Platform note:** airgapped and internal-platform targets should run on Linux or WSL2 for full functionality. Native Windows Git Bash lacks auto-download of `python3`/`jq` and has partial process-cleanup support — WSL2 avoids these limitations entirely.

---

## 0 — Validate on gitlab.com first (do this before steps 1–6)

Prove the skill works end to end against the **public** instance while you still have internet. Everything after this step assumes the mechanics already work, so a failure here is much cheaper to diagnose than the same failure inside the airgap.

The `catalog` profile ships pointed at `https://gitlab.com` with the four `lobster-thermidor/devops/ci-catalogue` components. That catalogue is **private**: anonymous API reads return `404`, so a `read_api` PAT is required.

### 0.1 — Create a `read_api` PAT

1. gitlab.com → **Preferences → Access tokens → Add new token**.
2. Scope: **`read_api`** only. Nothing else is needed — the skill never writes.
3. Expiry: shortest that covers your migration window.
4. The token owner must have at least Reporter on `lobster-thermidor/devops/ci-catalogue`.

### 0.2 — Export it under the configured name

`settings.catalog.auth_token_env` ships as `GITLAB_READ_TOKEN`, so that is the env var the skill reads. Put it in your shell profile so every run inherits it:

```bash
echo 'export GITLAB_READ_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx' >> ~/.zshrc   # or ~/.bashrc
source ~/.zshrc
```

Only the **name** lives in `scanner-preferences.yaml`; the value stays in your environment and is passed to `curl --config`, never on a command line where `ps` could read it. Never commit the token.

If preflight reports `catalog auth: env var GITLAB_READ_TOKEN ... is not set`, the export did not reach the shell running the scan. That hard failure is deliberate: without it, a tokenless run would quietly fall back to the vendored snapshots and *look* like a successful live test.

### 0.3 — Verify, in order

```bash
# 1. Resolver logic, no network: four self-test lines, exit 0
bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh self-test

# 2. Preferences load: expect GITLAB_INSTANCE=https://gitlab.com,
#    CATALOG_AUTH_ENV=GITLAB_READ_TOKEN, four RUN_* flags true
bash plugins/appsec/skills/appsec-scan/scripts/load-prefs.sh \
  plugins/appsec/skills/appsec-scan/config/scanner-preferences.yaml

# 3. LIVE resolution against gitlab.com — the actual PAT test.
#    Expect: "<component>@<tag> [online]"
#    "[offline-fallback]" means the token was rejected; fix before continuing.
#    QUOTE '~latest' — zsh (the macOS default shell) expands a bare ~latest
#    as a home directory and the command dies with "no such user".
bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh \
  resolve https://gitlab.com \
  lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast \
  '~latest' /tmp/cat-live GITLAB_READ_TOKEN

# 4. Orchestration without containers: every scanner command printed,
#    credentials shown masked.
#    RUNTIME is required: run-scan.sh self-loads scanner-preferences.yaml, but
#    load-prefs.sh does not emit RUNTIME — normally the SKILL.md flow exports it
#    (Step 1). Standalone, pass it yourself or the run exits 2.
RUNTIME=$(bash plugins/appsec/skills/appsec-scan/scripts/detect-runtime.sh) \
  APPSEC_PROFILE=catalog \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh --dry-run

# 5. One real scan against a throwaway repo (pulls the public images)
RUNTIME=$(bash plugins/appsec/skills/appsec-scan/scripts/detect-runtime.sh) \
  APPSEC_PROFILE=catalog \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh

# 6. Test suite
python3 -m pytest plugins/appsec/skills/appsec-scan/tests/ -q
```

Check 3 is the one that matters: `[online]` proves live catalog resolution works with your PAT. `[offline-fallback]` is the skill degrading gracefully, **not** a pass.

### 0.4 — Compare live tags against the vendored snapshots

While you still have live access, resolve all four components and compare what came back with `reference/catalog/`. The vendored snapshots are what the airgap will actually serve, so any gap here becomes a stale component in there.

```bash
for p in fortify-sast/fortify-sast dependency-scanning/dependency-scanning \
         secret-detection/secret-detection container-scanning/container-scanning; do
  bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh resolve https://gitlab.com \
    "lobster-thermidor/devops/ci-catalogue/$p" '~latest' /tmp/cat-live GITLAB_READ_TOKEN
done
diff <(cd /tmp/cat-live/lobster-thermidor/devops/ci-catalogue && find . -mindepth 3 -maxdepth 3 -type d | sort) \
     <(cd plugins/appsec/skills/appsec-scan/reference/catalog/lobster-thermidor/devops/ci-catalogue && find . -mindepth 3 -maxdepth 3 -type d | sort)
```

Any difference means a snapshot is behind. Refresh it via UPDATE-GUIDE.md Scenario 6 **before** step 1 — you cannot do it once you are inside the airgap.

Only after all six checks pass, continue to step 1. Then revoke the PAT — it has no role inside the airgap, where step 4 sets `catalog.mode: offline`.

---

## 1 — Mirror scanner images

Pull the four scanner images from their public source and push them to your internal JFrog registry. The exact image refs come from the `catalog` profile in `config/scanner-preferences.yaml`:

| Category | Public image (from `catalog` profile) | Internal target |
|---|---|---|
| SAST | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sca:25.2.0-jdk17-review` | `jfrog.internal/security/fortify-sca:25.2.0-jdk17-review` |
| Dependency Scanning | `registry.gitlab.com/security-products/dependency-scanning:2` | `jfrog.internal/security/dependency-scanning:2` |
| Secret Detection | `registry.gitlab.com/security-products/secrets:7` | `jfrog.internal/security/secrets:7` |
| Container Scanning | `registry.gitlab.com/security-products/container-scanning:8` | `jfrog.internal/security/container-scanning:8` |

```bash
for pair in \
  "registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sca:25.2.0-jdk17-review jfrog.internal/security/fortify-sca:25.2.0-jdk17-review" \
  "registry.gitlab.com/security-products/dependency-scanning:2 jfrog.internal/security/dependency-scanning:2" \
  "registry.gitlab.com/security-products/secrets:7 jfrog.internal/security/secrets:7" \
  "registry.gitlab.com/security-products/container-scanning:8 jfrog.internal/security/container-scanning:8"; do
  src="${pair% *}"; dst="${pair##* }"
  docker pull "$src" && docker tag "$src" "$dst" && docker push "$dst"
done
```

Adjust the `jfrog.internal/security/` prefix to your actual internal registry path.

---

## 2 — Host tool artifacts

The skill fetches `jq` and (in v3.1+) a portable `python3` tarball from a platform artifact server when the tool is not on `PATH`. Host the binaries at paths matching the install_url templates (see step 4):

- **jq binaries:** one per `{os}/{arch}` (e.g. `linux/amd64/jq`, `darwin/arm64/jq`)
- **portable python3 tarballs:** one per `{os}/{arch}` (e.g. `linux/amd64/python3.tar.gz`)

Upload these to your internal JFrog Generic repository or equivalent artifact server. The URL template uses `{os}` and `{arch}` as literal placeholders filled from `uname` at runtime.

---

## 3 — Configure the `company` profile

Edit `config/scanner-preferences.yaml`, `company:` block:

```yaml
company:
  gitlab_instance: https://gitlab.internal.company.com   # your internal GitLab
  categories:
    sast:
      component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
      version: "25.2.0"          # pin exact tag for reproducibility
      image: jfrog.internal/security/fortify-sca:25.2.0-jdk17-review
      runner: fortify-sast.sh
      enabled: true
    dependency_scanning:
      component: lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning
      version: "1.0.0"
      image: jfrog.internal/security/dependency-scanning:2
      runner: gitlab-dependency-scanning.sh
      enabled: true
    secret_detection:
      component: lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection
      version: "1.0.0"
      image: jfrog.internal/security/secrets:7
      runner: secret-detection.sh
      enabled: true
    container_scanning:
      component: lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning
      version: "1.0.0"
      image: jfrog.internal/security/container-scanning:8
      runner: gitlab-container-scanning.sh
      enabled: true
```

**Note:** the shipped `company:` profile uses `~latest` for all four `version:` fields. As part of this step, change each to the exact tag you want pinned (e.g. `"25.2.0"` as shown above) — `~latest` resolves to a different tag on each run and defeats airgap reproducibility. The ADVISORY line will fire when you need to bump a pin.

---

## 4 — Update `settings:` for airgap

In the `settings:` block of `config/scanner-preferences.yaml`:

```yaml
settings:
  airgap: true
  catalog:
    mode: offline                  # skip live catalog; use reference/catalog/ snapshots
    auth_token_env: GITLAB_READ_TOKEN   # read_api PAT for internal GitLab; unused (and not
                                        # required by preflight) while catalog.mode: offline
  jq:
    prefer: host
    install_url: "https://jfrog.internal/artifactory/tools/jq/{os}/{arch}/jq"
  python:
    prefer: host
    install_url: "https://jfrog.internal/artifactory/tools/python3/{os}/{arch}/python3.tar.gz"
  container_registry:
    user_env: CS_REGISTRY_USER
    password_env: CS_REGISTRY_PASSWORD
```

Set `default_profile: company` (or `export APPSEC_PROFILE=company` before each run). With `airgap: true`, any profile pointing at gitlab.com is refused at load time.

---

## 5 — Refresh vendored catalog snapshots

The vendored snapshots in `reference/catalog/` are used when `catalog.mode: offline` or catalog resolution fails. Refresh them using the internal GitLab instance (Scenario 6 in UPDATE-GUIDE.md):

```bash
for component in \
  "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast 25.2.0" \
  "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning 1.0.0" \
  "lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection 1.0.0" \
  "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning 1.0.0"; do
  path="${component% *}"; ver="${component##* }"
  GITLAB_READ_TOKEN="$GITLAB_READ_TOKEN" \
    bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh \
    resolve "https://gitlab.internal.company.com" "$path" "$ver" /tmp/catalog-refresh "GITLAB_READ_TOKEN"
done
```

Copy `template.yml`, `README.md`, `AGENTS.md` from the refresh output into `reference/catalog/<path>/<ver>/`.

---

## 6 — Verification checklist

Run each check in order; fix before proceeding to the next.

```bash
# 1. load-prefs smoke: must emit company profile vars, no errors
bash plugins/appsec/skills/appsec-scan/scripts/load-prefs.sh \
  plugins/appsec/skills/appsec-scan/config/scanner-preferences.yaml

# 2. catalog.sh self-test (offline mode)
CATALOG_MODE=offline bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh \
  resolve https://gitlab.internal.company.com \
  lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast 25.2.0 \
  /tmp/cat-test ""

# 3. Dry-run (no containers, verify orchestration)
#    RUNTIME must be passed explicitly — see step 0.3 check 4.
RUNTIME=$(bash plugins/appsec/skills/appsec-scan/scripts/detect-runtime.sh) \
  APPSEC_PROFILE=company \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh --dry-run

# 4. One live scan (pulls images from internal registry, runs all enabled scanners)
RUNTIME=$(bash plugins/appsec/skills/appsec-scan/scripts/detect-runtime.sh) \
  APPSEC_PROFILE=company \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh

# 5. pytest
python3 -m pytest plugins/appsec/skills/appsec-scan/tests/ -v
```

All five checks passing = migration complete. For ongoing maintenance see UPDATE-GUIDE.md Scenario 6 (quarterly snapshot refresh) and PREFERENCES.md for profile-switching guidance.

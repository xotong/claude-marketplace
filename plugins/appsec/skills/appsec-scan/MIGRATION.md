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
#    credentials shown masked. run-scan.sh self-loads preferences and
#    self-detects the container runtime, so this works standalone.
APPSEC_PROFILE=catalog \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh --dry-run

# 5. One real scan against a throwaway repo (pulls the public images)
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

Only after all six checks pass, continue to step 1.

Whether to revoke this gitlab.com PAT afterwards depends on step 4: it is only needed for reads against **gitlab.com**, so it has no role inside the airgap. Your internal instance may need its own separate PAT — see "Do you need `auth_token_env`?" in step 4.

---

## 1 — Mirror scanner images

Pull the four scanner images from their public source and push them to your internal JFrog registry. The exact image refs come from the `catalog` profile in `config/scanner-preferences.yaml`:

| Category | Public image (from `catalog` profile) | Internal target |
|---|---|---|
| SAST | `registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/fortify-sca:25.2.0-jdk17-review` | `jfrog.internal/security/fortify-sca:25.2.0-jdk17-review` |
| Dependency Scanning | `registry.gitlab.com/security-products/dependency-scanning:2` | `jfrog.internal/security/dependency-scanning:2` |
| Secret Detection | `registry.gitlab.com/security-products/secrets:7` | `jfrog.internal/security/secrets:7` |
| Container Scanning | `registry.gitlab.com/security-products/container-scanning:8` | `jfrog.internal/security/container-scanning:8` |

```bash
for pair in \
  "registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/fortify-sca:25.2.0-jdk17-review jfrog.internal/security/fortify-sca:25.2.0-jdk17-review" \
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
  auth_token_env: ""      # internal instance serves the catalogue anonymously;
                          # overrides settings.catalog.auth_token_env
  categories:
    sast:
      component: lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast
      version: "25.2.0"          # pin exact tag for reproducibility
      image: jfrog.internal/security/fortify-sca:25.2.0-jdk17-review
      runner: fortify-sast.sh
      enabled: true
    dependency_scanning:
      component: lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning
      version: "1.1.0"
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
      version: "1.1.0"
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
    auth_token_env: GITLAB_READ_TOKEN   # default for profiles that do not set their
                                        # own; the company profile below sets ""

  jq:
    prefer: host
    install_url: "https://jfrog.internal/artifactory/tools/jq/{os}/{arch}/jq"
  python:
    prefer: host
    install_url: "https://jfrog.internal/artifactory/tools/python3/{os}/{arch}/python3.tar.gz"
  container_registry:
    user_env: CS_REGISTRY_USER          # leave the VARS unset for an anonymous-pull registry
    password_env: CS_REGISTRY_PASSWORD
```

Set `default_profile: company` (or `export APPSEC_PROFILE=company` before each run). With `airgap: true`, any profile pointing at gitlab.com is refused at load time.

### There is no catalog mode to choose

Components are always resolved live against the active profile's
`gitlab_instance` — which, inside your airgap, is your own internal GitLab. If
that fetch fails for any reason, `catalog.sh` falls back to the vendored
snapshots automatically and reports `[offline-fallback]`. That fallback is the
airgap guarantee; it needs no configuration.

A forced-offline setting existed until 2026-07-25 and was removed. It gave
nothing the design did not already provide — exact `version:` pins give
reproducibility, the fallback gives resilience — while silently disabling image
and contract drift detection, and risking serving snapshots vendored from
gitlab.com as though they were your internal components.

### Do you need `auth_token_env`?

It authenticates **GitLab API reads only** (tags, `template.yml`, `README.md`,
`AGENTS.md`). It is never used to pull scanner images — those use
`container_registry`, so an anonymous-pull JFrog mirror needs nothing here.

Being inside the network does not authenticate you to GitLab. Test whether your
instance serves the projects anonymously:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  https://gitlab.internal.company.com/api/v4/projects/<group>%2F<project>/repository/tags
```

`200` → set `auth_token_env: ""`. `401`/`404` → keep the PAT and export it.

**Careful:** when `auth_token_env` names a variable and `mode` is `online`,
preflight fails if that variable is unset. That is deliberate — it stops a
tokenless run silently degrading to snapshots and looking like a live check — but
it means naming a var "just in case" blocks every run until a token exists.

---

## 5 — Refresh vendored catalog snapshots

The vendored snapshots in `reference/catalog/` are the automatic fallback when catalog resolution fails. Re-vendor them **from your internal instance** so the fallback serves the components you actually published, not the gitlab.com originals:

```bash
cd plugins/appsec/skills/appsec-scan
bash scripts/revendor.sh https://gitlab.internal.company.com
```

Add a token env var name as a second argument if your instance requires auth. The script refuses to vendor any component that resolved `[offline-fallback]`, so it cannot quietly confirm a stale snapshot against itself.



---

## 6 — Verification checklist

Run each check in order; fix before proceeding to the next.

```bash
# 1. load-prefs smoke: must emit company profile vars, no errors
bash plugins/appsec/skills/appsec-scan/scripts/load-prefs.sh \
  plugins/appsec/skills/appsec-scan/config/scanner-preferences.yaml

# 2. catalog.sh self-test (offline mode)
bash plugins/appsec/skills/appsec-scan/scripts/catalog.sh \
  resolve https://gitlab.internal.company.com \
  lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast 25.2.0 \
  /tmp/cat-test ""

# 3. Dry-run (no containers, verify orchestration)
APPSEC_PROFILE=company \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh --dry-run

# 4. One live scan (pulls images from internal registry, runs all enabled scanners)
APPSEC_PROFILE=company \
  bash plugins/appsec/skills/appsec-scan/scripts/run-scan.sh

# 5. Coverage honesty: every enabled category must appear in scanners_run, and
#    anything without a report must appear in missing_report with coverage_complete
#    false. A category missing from BOTH lists is a bug — report it.
cat .appsec-results/scan-coverage.json

# 6. Contracts must match the components your instance actually serves
#    (regenerate per UPDATE-GUIDE.md Scenario 6 if this reports CONTRACT-DRIFT)
bash plugins/appsec/skills/appsec-scan/scripts/resolve-components.sh

# 7. pytest
python3 -m pytest plugins/appsec/skills/appsec-scan/tests/ -v
```

All seven checks passing = migration complete. For ongoing maintenance see UPDATE-GUIDE.md Scenario 6 (quarterly snapshot refresh) and PREFERENCES.md for profile-switching guidance.

# appsec-scan

**Run the same security scanners CI runs — on your machine, before you push.**

If CI is going to flag it, you find out now instead of after the pipeline goes red.
The skill scans your working tree, tells you what it found, offers to fix what it can
on a throwaway branch, and writes a triage plan for the rest.

```
You: /appsec-scan
```

That runs everything. If you'd rather pick, just say what you want in plain English —
the skill works out which scanner you mean:

| You say | You get |
|---|---|
| "do all security scans", "is this safe to push" | all four scanners |
| "do a SAST scan", "scan my code", "run Fortify" | SAST only |
| "check my dependencies", "any vulnerable libraries", "CVE check" | dependency scanning only |
| "any hardcoded secrets", "did I commit a key" | secret detection only |
| "do a container scan", "scan my Docker image" | container scanning only |

**Not sure which you need?** Just say "run a security scan" and you'll get a checklist
to pick from, described in plain language — no need to know what SAST or SCA mean.
Picking nothing in particular gets you everything, which is the right default.

> A scoped scan always tells you which categories it *didn't* cover, and never reports
> "clear to push" on its own. Run the full set before you actually push.

Everything below is context for when something goes wrong or you want more control.

---

## Before your first scan

You need two things:

| Requirement | Check it |
|---|---|
| **Docker or Podman**, running | `docker info` (or `podman info`) |
| **python3** on PATH | `python3 --version` |

> Without `python3` the scan still runs, but severity normalization, triage, and the
> gate degrade to raw counts with `UNKNOWN` status. Your platform admin can point
> `settings.python.install_url` at an internal tarball to auto-provision it.

### One-time setup on gitlab.example.com (`platform-engineering` profile)

1. **Log in once with `glab`.** The skill reuses this login for catalogue lookups and
   for GitLab-native dependency matching. Nothing else to export.
   ```bash
   glab auth login --hostname gitlab.example.com
   ```
   Prefer a personal access token instead? Put it in `APPSEC_GITLAB_TOKEN` with the
   **`api`** scope. `read_api` is enough for catalogue lookups but not for the matcher,
   which uploads your manifests and starts a pipeline.
2. **Make sure your team's group has Developer access** to
   `platform-engineering/skillshub/appsec-sbom-matcher` (the platform team invites whole
   groups, not individuals — ask once per team). Dependency scanning sends only
   your lockfiles/manifests there (never source), gets GitLab's own findings back, and
   deletes the upload. Without access, or with `APPSEC_REMOTE_MATCH=off`, the skill
   falls back to an offline Trivy match and labels the results as not GitLab's.
3. **SAST (Fortify) only, until the internal container registry is live:** log Docker
   in to registry.gitlab.com with the read-only token the platform team gives you
   through the password manager. Once the images move to the self-hosted registry, run
   `docker logout registry.gitlab.com`; no login is needed after that.
   ```bash
   docker login registry.gitlab.com -u <deploy-token-username>
   ```
   On Apple Silicon the Fortify image runs under emulation, so expect a few minutes
   per build unit.
4. **Check it works** from a repo you want to scan:
   ```bash
   bash <path-to-skill>/scripts/run-scan.sh --only dependency_scanning
   ```
   Look for `REMOTE-MATCH: language=... status=ok`. A `REMOTE-MATCH-REASON` with 401 or
   403 means step 1 or step 2 is missing.

**`glci` is optional.** It is only used by profiles that set `engine: glci` (the
shipped `platform-engineering` default does, for secret detection and container
scanning) to run the CI/CD Catalog component's real job locally instead of this
skill's own docker-based runner script. Without it, or if it is unhealthy, those
categories fall back to the docker engine automatically and say so
(`ADVISORY:`) — nothing fails. Install it from
[gitlab.org/gitlab-org/ci-cd/runner-tools/glci](https://gitlab.com/gitlab-org/ci-cd/runner-tools/glci)
if you want the closer-to-CI local run; it needs Docker or Podman itself.

The skill ships pointed at the **`platform-engineering`** profile by default
(`gitlab.example.com`). Ask your platform admin whether that is right for you, or
switch profiles explicitly:

```bash
export APPSEC_PROFILE=company     # internal GitLab + internal registry
```

If your profile's catalogue needs authentication, export a `read_api` token under the
name it expects (`APPSEC_GITLAB_TOKEN` for `platform-engineering`,
`GITLAB_READ_TOKEN` for `catalog`):

```bash
export APPSEC_GITLAB_TOKEN=glpat-xxxxxxxxxxxx
```

If you skip this and already run `glab auth login --hostname <your-instance>`, the
skill falls back to `glab`'s own stored token automatically
(`settings.catalog.glab_fallback`, on by default) — nothing else to export. Whether
you need a token at all depends on your profile — see
[Do I need a token?](#do-i-need-a-token) below. Put the export in your shell profile
(`~/.bashrc` / `~/.zshrc`) so you set it once.

---

## Your first scan

From the root of the repo you want to scan:

```
/appsec-scan
```

The skill will:

1. Check your environment and fail fast with a specific message if something's missing.
2. Work out which scanners apply to your project (Maven? Go? a Dockerfile?).
3. Run them — SAST, dependency scanning, and secret detection in parallel; container
   scanning after.
4. Print a severity summary.
5. Offer to fix what it can, on a new branch, after asking you once — you choose
   whether it fixes everything actionable automatically (up to 5 iterations) or
   walks you through each fix one at a time.
6. Write `.appsec-results/TRIAGE.md` for anything it couldn't fix.

Nothing is committed, pushed, or changed on your current branch without you saying yes.

### What you get

Everything lands in `.appsec-results/` (which ignores itself — your repo's `.gitignore`
needs no change):

| File | What it's for |
|---|---|
| `TRIAGE.md` | **Start here.** Human-readable plan: what was fixed, what you must fix, what to dismiss in GitLab and how to word it |
| `findings.triaged.json` | Every finding with severity, location, and a verification status |
| `scan-coverage.json` | Which scanners actually ran — read this before trusting an all-clear |
| `gl-*.json`, `*.fpr` | Raw scanner reports, for uploading or deeper inspection |

### Reading the result

The one thing worth internalising:

> **A scanner that did not run is not a pass.** If a scanner was selected but produced
> no report, that becomes a HIGH-severity coverage finding and fails the gate. "No
> findings" and "didn't scan" are deliberately not the same outcome.

One thing worth knowing before you act on the dependency numbers — check which source
produced them, printed as `Dependency Scanning source:` in the summary and recorded in
`scan-coverage.json`'s `dependency_scanning.source`:

> **`offline-trivy`** (every profile without `remote_match_project` configured, e.g.
> `catalog`/`company`): GitLab matches your SBOM against its own advisory database
> server-side, behind an API that only accepts a real CI job token, so a plain local run
> cannot reproduce it. Instead the skill matches the SBOM offline with the Trivy bundled
> in the container-scanning image. Treat those findings and their fix versions as an
> early triage signal; they will **not** match the post-push Vulnerability Report
> exactly, in content or in count.
>
> **`gitlab-native`** (profiles with `remote_match_project` set, e.g.
> `platform-engineering`, unless `APPSEC_REMOTE_MATCH=off`): the skill uploads only your
> dependency manifests/lockfiles (never source) to a pre-configured helper GitLab
> project and triggers a real pipeline there with a real `CI_JOB_TOKEN`, so this result
> **is** GitLab's own server-side match — no Trivy caveat applies. See
> [`reference/remote-matcher/README.md`](reference/remote-matcher/README.md) for what
> that helper project is and how it is set up. If the matcher is unusable before any
> pipeline runs (no token, project unreachable, wrong access), the whole category falls
> back to `offline-trivy` instead and says so. Once at least one pipeline has run, a
> single language whose matcher pipeline then fails does **not** fall back to Trivy for
> that language — it is a coverage gap instead (the languages that did succeed keep
> their GitLab-native report).
>
> Every other category is byte-for-byte the CI scanner (or, with `engine: glci`, the CI
> component's own job run locally).

Findings carry a `verification_status`:

| Status | Meaning |
|---|---|
| `confirmed_true_positive` | Real. Fix it. |
| `likely_false_positive` | Probably noise — but it still counts against the gate. Dismiss it in GitLab's Vulnerability Report with a justification; don't just ignore it. |
| `not_fixable_locally` | Needs infra, a dependency upgrade, or a decision above your pay grade. |
| `blocked_registry_gap` | There *is* a fix — the version just isn't in our mirror yet. See TRIAGE.md §3b for the batched list to send your platform team. Nothing for you to do until it's mirrored. |
| `needs_human_review` | The skill isn't confident. Look at it yourself. |

---

## Common tasks

Most of these are easiest to ask for in plain language — the skill drives the scripts
for you:

> "rescan just the SAST findings"
> "show me what you'd run without running it"
> "scan this as a Go project"

**Force a language** when detection guesses wrong:

```bash
FORTIFY_LANGUAGE=go /appsec-scan
```

Supported: `maven`, `gradle`, `python`, `javascript`, `go`.

**The Fortify JDK is picked for you.** For Java projects the scan reads the compile
target out of your `pom.xml` or `*.gradle[.kts]` and selects the matching analyzer
image, so a Java 21 project is not built by a JDK 17 analyzer:

```
INFO: [Fortify SCA] Project targets Java 21; selecting jdk21-review
```

Override only if that is wrong for your repo:

```bash
FORTIFY_VARIANT=jdk17-review /appsec-scan
```

**Point at a subdirectory** in a monorepo (defaults to `src`):

```bash
SOURCE_PATH=services/api /appsec-scan
```

**Pick which Dockerfile(s)** container scanning builds and scans — the skill otherwise
finds every Dockerfile/Containerfile in the repo on its own (so a monorepo with
Dockerfiles only under `services/*` is no longer skipped):

```bash
DOCKERFILE=services/api/Dockerfile /appsec-scan            # exactly one
APPSEC_DOCKERFILES=services/api/Dockerfile,services/web/Dockerfile /appsec-scan  # a subset
```

More than one Dockerfile in scope gets its own report
(`gl-container-scanning-report-<slug>.json`); exactly one keeps the plain name.

**Switch profile for one run:**

```bash
APPSEC_PROFILE=catalog /appsec-scan
```

**Force the offline dependency match** even on a profile with GitLab-native matching
configured (e.g. to sanity-check the two against each other, or when the helper
project is unreachable):

```bash
APPSEC_REMOTE_MATCH=off /appsec-scan
```

### Running the scanner directly

`run-scan.sh` is safe to invoke on its own — it self-loads preferences and detects the
container runtime if they aren't already set. You need the skill's install path, which
varies by machine:

```bash
# Find it once, then reuse:
SKILL=$(dirname "$(find ~/.claude -name run-scan.sh -path '*appsec-scan*' 2>/dev/null | head -1)")

cd /path/to/your/repo
"$SKILL/run-scan.sh" --only sast     # one category, much faster while iterating
"$SKILL/run-scan.sh" --dry-run       # print every container command, credentials redacted
```

Valid `--only` categories: `sast`, `dependency_scanning`, `secret_detection`,
`container_scanning`.

---

## Troubleshooting

### "requested profile 'x' not found"
`APPSEC_PROFILE` names a profile that isn't in `config/scanner-preferences.yaml`. The
error lists the valid ones; you can also read them off the file:

```bash
sed -n '/^profiles:/,$p' config/scanner-preferences.yaml | grep -E '^  [a-z_]+:$'
```

### "the component's image is not available from this registry"
Your admin's config leaves `image:` to be derived from the CI component, and the tag the
component asks for isn't in your registry yet. The message names the exact ref — send it
to your platform team to mirror. The scan **stops** here rather than skipping the
scanner, because a skipped scanner would read as a clean result for a category that
never ran.

### "Cannot connect to the Docker daemon"
Docker isn't running, or your user isn't in the `docker` group.

```bash
docker info                      # confirm the daemon is up
sudo usermod -aG docker "$USER"  # then log out and back in
```

On WSL2, enable Docker Desktop's integration for your distro under
**Settings → Resources → WSL Integration**.

### The catalogue fetch failed but the scan continued
That's intended, *if* it said `[offline-fallback]`. `catalog.sh` falls back to the
vendored snapshots in `reference/catalog/` and scans keep working with no network:
the snapshots carry the same `template.yml` the live read would have returned, so
version resolution, drift checks **and the scanner image** all still resolve — from a
snapshot rather than from your instance. If those snapshots were vendored somewhere
else, that is your admin's problem to fix (MIGRATION.md "Re-vendor"), not yours.

`[offline-fallback: unauthorized]` is a different thing and does **not** continue: your
instance answered and refused the token. Fix or set the PAT named by
`settings.catalog.auth_token_env`. A snapshot is no substitute here — it cannot tell you
the component changed, so continuing would look like a live check that passed.

### It says CONFIG-ERROR and stopped
Something you (or your admin) configured is wrong: a registry refused our credentials, a
`ca_bundle` path is not readable, a mirror needs a token it was not given. The line names
the exact setting or env var. Nothing else is tried on purpose — a rejected credential is
not fixed by another image, tag or endpoint, and every alternative fails the same way,
leaving you with a scan that reads like a result. Fix what the line names and re-run.

Catalog resolution (`catalog.sh`) reports four specific shapes of this:

- **404, no credential attached** — internal/private CI/CD Catalog projects answer `404`
  to an anonymous read (not `401`), which looks like a missing project rather than a
  missing token. Export the token named by `settings.catalog.auth_token_env`, or run
  `glab auth login --hostname <your-instance>` so the `glab` fallback can supply one.
- **404, even with a token attached** — the component path is wrong, or this identity
  cannot see it. Check the path and the token owner's access.
- **TLS verification failed** — almost always corporate TLS inspection (a proxy
  re-signing with an internal CA `curl` does not trust), not an outage. Set
  `settings.ca_bundle` to that CA's PEM file.
- **No releases or tags** — `version: ~latest` cannot resolve on an instance where the
  component was never tagged/released. Ask the platform team to tag and release it, or
  pin an exact `version:` once one exists.

### SAST was skipped
Fortify needs a recognisable project. It looks for `pom.xml`, `build.gradle`,
`package.json`, `requirements.txt` / `pyproject.toml`, or `go.mod` at the repo root.
Monorepo with the build file in a subdirectory? Set the language explicitly:

```bash
FORTIFY_LANGUAGE=maven SOURCE_PATH=services/api /appsec-scan
```

### Everything says UNKNOWN
`python3` wasn't found, so normalization degraded to raw counts. Install `python3`, or
ask your admin to set `settings.python.install_url`.

### Do I need a token?

Only if your profile's GitLab instance requires authentication to read the CI/CD
Catalog. Check `auth_token_env` for your profile in `config/scanner-preferences.yaml`:

- **Named env var** (e.g. `APPSEC_GITLAB_TOKEN` for `platform-engineering`,
  `GITLAB_READ_TOKEN` for `catalog`) → you need a `read_api` PAT (or OAuth token) in
  that variable. If it's unset, the skill falls back to `glab config get token` for
  that instance's host (`settings.catalog.glab_fallback`, on by default) before
  preflight fails — so a host already `glab auth login`-ed against the instance needs
  no separate export.
- **Empty (`""`)** → your instance serves the catalogue anonymously. No token needed.

The dependency matcher (`remote_match_project`) is the exception: it always needs a
login, because it uploads a bundle and starts a pipeline. `glab auth login` covers it;
a personal token needs the `api` scope, not just `read_api`.

The token is used for the **GitLab API only** (sent as `Authorization: Bearer`) —
never for pulling images. Image registry credentials are separate
(`settings.container_registry.*`), and `engine: glci` never forwards this token into
the job it runs (`--no-token --secrets none`) — only reads catalogue metadata with it.

---

## Platform support

| Platform | Status | Notes |
|---|---|---|
| Linux (Ubuntu / Debian) | Supported | Docker or Podman; host `python3` preferred |
| macOS | Supported | Docker Desktop, Colima, or Podman |
| **WSL2 (Windows)** | Supported — **use this on Windows** | Avoids every native-Windows caveat below |
| Native Windows (Git Bash + Docker Desktop) | Best effort | Claude Code can only run `.sh` scripts through Git Bash. Volume-mount translation may need `MSYS_NO_PATHCONV=1`; timeout cleanup is best-effort; `python3`/`jq` auto-download does not work. Prefer WSL2. |
| PowerShell / cmd | Not supported | — |

---

## What this skill deliberately does not do

- **DAST or API security.** Both catalogue components need a deployed, running,
  authenticated target — a URL plus login selectors, or a mandatory `target-url` — which
  a working-tree scan cannot provide. Deliberately declined, not missing: see
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#catalogue-components-this-skill-does-not-cover).
  Use the [`appsec-dast-sim`](../appsec-dast-sim/README.md) skill for design-time
  analysis, and those components in CI after a deploy job.
- **Push, or upload results anywhere.** Everything stays in `.appsec-results/`. The
  Fortify component's SRM upload path is not part of the local runner.
- **Block your commit.** It reports; you decide. Findings you don't fix are meant to be
  dismissed in GitLab's Vulnerability Report with a justification — `TRIAGE.md` gives
  you the wording.

---

## More

| Document | For |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How it works internally, with diagrams |
| [`config/PREFERENCES.md`](config/PREFERENCES.md) | Admins: every config key and how to change it |
| [`UPDATE-GUIDE.md`](UPDATE-GUIDE.md) | Maintainers: keeping runners in sync with the CI components |
| [`MIGRATION.md`](MIGRATION.md) | Admins: moving from the public catalogue to an internal instance |
| [`reference/remote-matcher/README.md`](reference/remote-matcher/README.md) | Admins: setting up the helper project for GitLab-native dependency-scanning matching |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

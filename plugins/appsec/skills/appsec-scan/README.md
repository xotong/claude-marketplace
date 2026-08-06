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

Then ask your platform admin which **profile** you should use. Profiles decide which
GitLab instance and which image registry the skill talks to:

```bash
export APPSEC_PROFILE=company     # internal GitLab + internal registry
```

If your profile's catalogue needs authentication, you also need a `read_api` token:

```bash
export GITLAB_READ_TOKEN=glpat-xxxxxxxxxxxx
```

Whether you need that token depends on your profile — see
[Do I need a token?](#do-i-need-a-token) below. Put both exports in your shell profile
(`~/.bashrc` / `~/.zshrc`) so you set them once.

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
5. Offer to fix what it can, on a new branch, after asking you once.
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

**Point at a subdirectory** in a monorepo (defaults to `src`):

```bash
SOURCE_PATH=services/api /appsec-scan
```

**Switch profile for one run:**

```bash
APPSEC_PROFILE=catalog /appsec-scan
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

### "No scanner image env vars are set"
Preflight found no configured scanners. You almost certainly haven't set
`APPSEC_PROFILE`, or you set it to a profile name that isn't in
`config/scanner-preferences.yaml`. Check the profile list:

```bash
grep -A1 "^profiles:" config/scanner-preferences.yaml
```

### "Cannot connect to the Docker daemon"
Docker isn't running, or your user isn't in the `docker` group.

```bash
docker info                      # confirm the daemon is up
sudo usermod -aG docker "$USER"  # then log out and back in
```

On WSL2, enable Docker Desktop's integration for your distro under
**Settings → Resources → WSL Integration**.

### The catalogue fetch failed but the scan continued
That's intended. `catalog.sh` falls back to the vendored snapshots in
`reference/catalog/` and says so. Scans keep working with no network. Only version
resolution and drift warnings are affected.

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

- **Named env var** (e.g. `GITLAB_READ_TOKEN`) → you need a `read_api` PAT in that
  variable. Preflight fails fast if it's unset, so a run can never quietly fall back to
  vendored snapshots and look like a live check.
- **Empty (`""`)** → your instance serves the catalogue anonymously. No token needed.

The token is used for the **GitLab API only** — never for pulling images. Image
registry credentials are separate (`settings.container_registry.*`).

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

- **DAST.** Needs a deployed target and a runner — that isn't a local pre-push check.
  Use the [`appsec-dast-sim`](../appsec-dast-sim/README.md) skill for design-time
  analysis, or the catalogue's `dast` / `api-security` components in CI.
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
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

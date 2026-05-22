# Skill Safety Scanner

LLM-as-judge CI scanner for Claude Code plugin instruction files. Evaluates skills,
agent definitions, and slash command definitions against five security risk categories.
Fails the pipeline if safety confidence falls below a configurable threshold.

Runs airgap: the only external call is to your internal LiteLLM endpoint.

---

## Quick start

### Step 1 — Add the component to your skills repo

In your team skills repo, create or update `.gitlab-ci.yml`:

```yaml
include:
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner-component/skill-scanner-component@~latest
```

That is the entire CI config change. Endpoint and default model are managed centrally by
the Platform Team — you don't need to know or configure them.

### Step 2 — Set the API key CI/CD variable

In your project: **Settings → CI/CD → Variables → Add variable**

| Key | Value | Flags |
|---|---|---|
| `LITELLM_API_KEY` | _(your key — ask Platform Team if you don't have one)_ | Masked ✓, Protected ✓ |

This is the only credential you manage. Never put it in `.gitlab-ci.yml`.

> Don't have a key yet? Raise a Jira ticket titled **"Onboard Claudecode"** and assign it to the Platform Team.

### Step 3 — Copy the example config (optional but recommended)

```bash
cp ci/skill-scanner/scanner-config.example.yaml scanner-config.yaml
# edit threshold or prompts as needed, then commit
git add scanner-config.yaml
git commit -m "ci: add skill scanner config"
```

The scanner reads `scanner-config.yaml` from the repo root at runtime. You can tune
the threshold or prompts without touching CI YAML or rebuilding the image. If the file
is absent, built-in defaults are used.

### Step 4 — View results in GitLab

- **MR UI → Tests tab** — each `SKILL.md`, agent, or command appears as a named test case. Failed files show the LLM's reasoning.
- **Pipeline → Artifacts** — download `scan-report.json` for the full structured output.

---

## Output format

```json
{
  "confidence_safe": 0.93,
  "risks": [],
  "reasoning": "The skill instructs Claude to summarise git diffs...",
  "verdict": "SAFE"
}
```

Pass condition: `confidence_safe >= threshold` AND verdict is not `REVIEW_NEEDED`
(unless `fail_on_review: false`, which is the default).

---

## Configuration reference

**What you configure** (the only things your team needs to touch):

| What | Where | Description |
|---|---|---|
| `LITELLM_API_KEY` | Project CI/CD variable (masked) | API key for the LLM gateway |
| `scanner-config.yaml` | Repo root (optional) | Tune threshold or prompts per-repo |

**Config file fields** (all optional — unset fields use image defaults):

```yaml
threshold: 0.85        # safety pass score, 0–1
model: "kimi-k2"       # override the model (rarely needed)
system_prompt: |
  ...
user_prompt: |
  ... {skill_content} ...
```

**Available component inputs** (override in your `include:` block only if needed):

| Input | Default | Description |
|---|---|---|
| `stage` | `test` | GitLab CI stage |
| `skills_dir` | `.` | Subdirectory to scan (default: repo root) |
| `threshold` | `0.85` | Safety pass score override |
| `fail_on_review` | `false` | Block pipeline on REVIEW_NEEDED verdict |
| `scanner_model` | `kimi-k2` | LiteLLM model name (leave as default unless asked by Platform Team) |
| `image` | `...skill-scanner:latest` | Pin to a specific image tag for reproducibility |

Example — stricter config for a security-sensitive repo:

```yaml
include:
  - component: gitlab.company.com/skillshub/claude-marketplace/skill-scanner-component/skill-scanner-component@~latest
    inputs:
      threshold: 0.92
      fail_on_review: true
```

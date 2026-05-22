# Skill Safety Scanner — Implementation

Python scanner + Docker image that backs the `skill-scanner-component` GitLab CI component.

The component spec and tenant/platform documentation live in `skill-scanner-component/`.

---

## Files

| File | Purpose |
|---|---|
| `scanner.py` | Scanner implementation — reads SKILL.md/agent/command files, calls LiteLLM, writes JUnit + JSON output |
| `Dockerfile` | Builds the scanner image — based on Python 3.12-slim, copies scanner.py and config.yaml |
| `config.yaml` | Baked-in defaults (prompts, threshold, model) — editable without a code change |
| `requirements.txt` | Python dependencies |
| `scanner-config.example.yaml` | Template tenants copy into their repo root to tune threshold/prompts |
| `.dockerignore` | Excludes `__pycache__` and local dev files from the image build |

---

## Building the image

```bash
docker build \
  -t registry.gitlab.company.com/skillshub/claude-marketplace/skill-scanner:latest \
  -t registry.gitlab.company.com/skillshub/claude-marketplace/skill-scanner:1.0.0 \
  ci/skill-scanner/

docker push registry.gitlab.company.com/skillshub/claude-marketplace/skill-scanner:latest
docker push registry.gitlab.company.com/skillshub/claude-marketplace/skill-scanner:1.0.0
```

See `skill-scanner-component/templates/README.md` for versioning discipline and publishing steps.

---

## Running locally

```bash
# With Docker
docker run --rm \
  -e SCANNER_ENDPOINT=https://litellm.company.com/v1 \
  -e SCANNER_API_KEY=your-key \
  -e SCANNER_SKILLS_DIR=/repo \
  -v /path/to/skills-repo:/repo \
  registry.gitlab.company.com/skillshub/claude-marketplace/skill-scanner:latest

# Without Docker (Python 3.12+)
pip install -r ci/skill-scanner/requirements.txt
SCANNER_ENDPOINT=https://litellm.company.com/v1 \
SCANNER_API_KEY=your-key \
SCANNER_SKILLS_DIR=/path/to/skills-repo \
python ci/skill-scanner/scanner.py
```

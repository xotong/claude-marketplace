FROM python:3.12-slim

LABEL org.opencontainers.image.title="xotong1 Skill Safety Scanner"
LABEL org.opencontainers.image.description="Scans Claude Code SKILL.md files for security risks using an LLM-as-judge pattern."
LABEL org.opencontainers.image.source="https://gitlab.company.com/skillshub/claude-marketplace"

WORKDIR /scanner

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scanner and built-in default config.
# The config is the primary thing teams will want to tweak — but they do so
# via scanner-config.yaml in their own repo, not by rebuilding this image.
COPY scanner.py config.yaml ./

# Standalone usage:   docker run --rm -e SCANNER_ENDPOINT=... -e SCANNER_API_KEY=... \
#                       -v $(pwd):/skills -e SCANNER_SKILLS_DIR=/skills image
# GitLab CI usage:    entrypoint is overridden by the component; see gitlab-component.yml
ENTRYPOINT ["python", "/scanner/scanner.py"]

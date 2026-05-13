FROM python:3.12-slim

LABEL org.opencontainers.image.title="Skill Safety Scanner"
LABEL org.opencontainers.image.description="Scans Claude Code SKILL.md files for security risks using an LLM-as-judge pattern."
LABEL org.opencontainers.image.source="https://gitlab.company.com/skillshub/claude-marketplace"

WORKDIR /scanner

# git is required for the targeted-scan path in CI (git diff to find changed SKILL.md files).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scanner and built-in default config.
# Prompts and threshold are tunable via scanner-config.yaml in the tenant's repo
# without rebuilding this image — see config.yaml for the defaults.
COPY scanner.py config.yaml ./

# Run as a non-root user. Required by most enterprise container admission policies
# and flagged by container security scanners (Trivy, Grype, Prisma) otherwise.
RUN adduser --disabled-password --gecos "" scanner
USER scanner

# Standalone usage:
#   docker run --rm \
#     -e SCANNER_ENDPOINT=https://litellm.company.com/v1 \
#     -e SCANNER_API_KEY=... \
#     -v $(pwd):/repo \
#     -e SCANNER_SKILLS_DIR=/repo \
#     <image>
#
# GitLab CI usage: entrypoint is overridden by the component (entrypoint: [""]);
# the script block calls "python /scanner/scanner.py" directly.
ENTRYPOINT ["python", "/scanner/scanner.py"]

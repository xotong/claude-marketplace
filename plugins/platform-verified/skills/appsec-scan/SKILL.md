---
name: appsec-scan
description: >
  Run a comprehensive local security scan before pushing to GitLab, covering SAST,
  SCA (dependency audit), secret scanning, DAST (if app is running), and config review.
  The goal is to surface and fix the same findings that GitLab CI security pipelines
  would report — before the commit is pushed.
  Use when the user says: "security scan", "security audit", "appsec", "check for
  vulnerabilities", "check for secrets", "dependency audit", "SAST scan", "SCA scan",
  "secrets scan", "scan before PR", "find security issues", "full pentest", "security
  check", "run all security checks", "vulnerability assessment", "check for CVEs".
  Do NOT activate for general code review, testing questions, or lint requests.
---

# AppSec Scan

Pre-empt GitLab CI security pipeline findings by running equivalent checks locally,
with actionable remediation for every issue found.

## Phase 1 — Detect Stack

Read the project root to identify languages, package managers, and frameworks.

```bash
ls -la
cat package.json 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -E '"name"|"dependencies"|"devDependencies"' | head -20 || true
cat requirements.txt 2>/dev/null | head -30 || cat pyproject.toml 2>/dev/null | head -30 || true
cat go.mod 2>/dev/null | head -10 || true
cat pom.xml 2>/dev/null | grep -E '<groupId>|<artifactId>|<version>' | head -20 || true
cat build.gradle 2>/dev/null | grep -E 'implementation|compile' | head -20 || true
cat Gemfile 2>/dev/null | head -20 || true
cat Cargo.toml 2>/dev/null | head -20 || true
cat composer.json 2>/dev/null | head -20 || true
```

Record: primary language(s), package manager(s), web framework(s), whether a server runs locally.

---

## Phase 2 — Secret Scanning (always run first)

Secrets in code are Critical severity. Run this phase regardless of what the user asked for.

### Step 2a: gitleaks (preferred)
```bash
which gitleaks 2>/dev/null && \
  gitleaks detect --source . --no-git \
    --report-format json \
    --report-path /tmp/gitleaks-report.json && \
  echo "gitleaks: clean" || \
  ([ -f /tmp/gitleaks-report.json ] && \
    python3 -c "
import json
d = json.load(open('/tmp/gitleaks-report.json'))
for f in d:
    print(f'CRITICAL SECRET: {f[\"RuleID\"]} in {f[\"File\"]}:{f[\"StartLine\"]}')
    print(f'  Match: {f[\"Secret\"][:20]}...')
" || echo "gitleaks not installed")
```

### Step 2b: detect-secrets (fallback)
```bash
which detect-secrets 2>/dev/null && \
  detect-secrets scan --baseline .secrets.baseline 2>/dev/null || \
  detect-secrets scan 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for fname, secrets in d.get('results', {}).items():
    for s in secrets:
        print(f'CRITICAL SECRET: {s[\"type\"]} in {fname}:{s[\"line_number\"]}')
" || true
```

### Step 2c: Pattern grep (always run as belt-and-braces)
```bash
# AWS keys
grep -rn --include="*.js" --include="*.ts" --include="*.py" --include="*.go" \
  --include="*.java" --include="*.rb" --include="*.php" --include="*.env" \
  -E 'AKIA[0-9A-Z]{16}' . 2>/dev/null && echo "CRITICAL: AWS Access Key found" || true

# Generic API key / token patterns in assignments
grep -rn --include="*.js" --include="*.ts" --include="*.py" --include="*.go" \
  --include="*.java" --include="*.rb" -iE \
  '(password|passwd|secret|api_key|apikey|auth_token|access_token|private_key)\s*[=:]\s*["\x27][A-Za-z0-9/+_\-]{8,}["\x27]' \
  . 2>/dev/null | grep -v "test\|spec\|mock\|fake\|example\|placeholder\|your_" || true

# .env files that should not be committed
git ls-files 2>/dev/null | grep -E '^\.env$|^\.env\.' | grep -v '\.env\.example\|\.env\.sample\|\.env\.template' && \
  echo "WARNING: .env file is tracked by git — remove and add to .gitignore" || true

# Private keys
git ls-files 2>/dev/null | xargs grep -l "BEGIN.*PRIVATE KEY\|BEGIN RSA PRIVATE\|BEGIN EC PRIVATE" 2>/dev/null && \
  echo "CRITICAL: Private key file committed to git" || true
```

---

## Phase 3 — SAST (Static Application Security Testing)

Run for every language detected in Phase 1. Semgrep is the universal tool; language-specific tools add depth.

### Universal: Semgrep
```bash
if which semgrep 2>/dev/null; then
  semgrep scan \
    --config=p/owasp-top-ten \
    --config=p/secrets \
    --config=p/sql-injection \
    --config=p/xss \
    --config=p/command-injection \
    --json \
    --output=/tmp/semgrep-results.json \
    --severity=ERROR \
    --severity=WARNING \
    . 2>/dev/null
  python3 -c "
import json
d = json.load(open('/tmp/semgrep-results.json'))
results = d.get('results', [])
print(f'Semgrep: {len(results)} finding(s)')
for r in sorted(results, key=lambda x: x.get('extra',{}).get('severity',''), reverse=True)[:20]:
    sev = r.get('extra',{}).get('severity','?')
    msg = r.get('extra',{}).get('message','')[:100]
    path = r.get('path','')
    line = r.get('start',{}).get('line','')
    print(f'  [{sev}] {path}:{line} — {msg}')
  " 2>/dev/null
else
  echo "semgrep not installed — install with: pip install semgrep"
fi
```

### Node.js / TypeScript
```bash
# ESLint with security plugin
if [ -f package.json ]; then
  npx eslint . --ext .js,.jsx,.ts,.tsx \
    --plugin security \
    --rule 'security/detect-eval-with-expression: error' \
    --rule 'security/detect-non-literal-regexp: warn' \
    --rule 'security/detect-object-injection: warn' \
    --rule 'security/detect-possible-timing-attacks: warn' \
    --rule 'security/detect-sql-literal-injection: error' \
    --rule 'no-eval: error' \
    --rule 'no-new-func: error' \
    2>/dev/null || true
  # Also run semgrep with JS/TS rules
  which semgrep 2>/dev/null && \
    semgrep --config=p/javascript --config=p/typescript --config=p/nodejs \
    --json --output=/tmp/semgrep-js.json . 2>/dev/null || true
fi
```

### Python
```bash
if [ -f requirements.txt ] || [ -f pyproject.toml ] || [ -f setup.py ]; then
  # bandit: Python SAST
  if which bandit 2>/dev/null; then
    bandit -r . \
      -f json \
      -o /tmp/bandit-results.json \
      -ll \
      --exclude ./node_modules,./venv,./.venv,./tests 2>/dev/null
    python3 -c "
import json
d = json.load(open('/tmp/bandit-results.json'))
results = d.get('results', [])
print(f'Bandit: {len(results)} finding(s)')
for r in results[:20]:
    print(f'  [{r[\"issue_severity\"]}] {r[\"filename\"]}:{r[\"line_number\"]} — {r[\"issue_text\"]}')
    print(f'    CWE: {r.get(\"issue_cwe\", {}).get(\"id\", \"?\")} | More: {r.get(\"more_info\",\"\")}')
    " 2>/dev/null
  else
    echo "bandit not installed — install with: pip install bandit"
  fi
  which semgrep 2>/dev/null && \
    semgrep --config=p/python --config=p/django --config=p/flask \
    --json --output=/tmp/semgrep-py.json . 2>/dev/null || true
fi
```

### Go
```bash
if [ -f go.mod ]; then
  # govulncheck: Go vulnerability database
  if which govulncheck 2>/dev/null; then
    govulncheck ./... 2>/dev/null
  else
    echo "govulncheck not installed — install with: go install golang.org/x/vuln/cmd/govulncheck@latest"
  fi
  # gosec: Go SAST
  if which gosec 2>/dev/null; then
    gosec -fmt json -out /tmp/gosec-results.json -severity high ./... 2>/dev/null
    python3 -c "
import json
d = json.load(open('/tmp/gosec-results.json'))
issues = d.get('Issues', [])
print(f'gosec: {len(issues)} finding(s)')
for i in issues[:20]:
    print(f'  [{i[\"severity\"]}] {i[\"file\"]}:{i[\"line\"]} — {i[\"details\"]}')
    print(f'    CWE: {i.get(\"cwe\",{}).get(\"id\",\"?\")} | Rule: {i[\"rule_id\"]}')
    " 2>/dev/null
  else
    echo "gosec not installed — install with: go install github.com/securego/gosec/v2/cmd/gosec@latest"
  fi
  which semgrep 2>/dev/null && semgrep --config=p/golang --json --output=/tmp/semgrep-go.json . 2>/dev/null || true
fi
```

### Java
```bash
if [ -f pom.xml ] || [ -f build.gradle ]; then
  which semgrep 2>/dev/null && \
    semgrep --config=p/java --config=p/spring --config=p/java-security-audit \
    --json --output=/tmp/semgrep-java.json . 2>/dev/null || true
  # Check for known critical vulnerabilities in declared deps
  grep -E 'log4j-(core|api).*:(1\.|2\.[0-9]\.|2\.1[0-4]\.)' pom.xml build.gradle 2>/dev/null && \
    echo "CRITICAL: Log4Shell-vulnerable log4j version detected" || true
fi
```

### Ruby
```bash
if [ -f Gemfile ]; then
  if which brakeman 2>/dev/null; then
    brakeman -f json -o /tmp/brakeman-results.json -q . 2>/dev/null
    python3 -c "
import json
d = json.load(open('/tmp/brakeman-results.json'))
warnings = d.get('warnings', [])
print(f'Brakeman: {len(warnings)} warning(s)')
for w in warnings[:20]:
    print(f'  [{w[\"confidence\"]}] {w[\"file\"]}:{w[\"line\"]} — {w[\"warning_type\"]}: {w[\"message\"]}')
    " 2>/dev/null
  else
    echo "brakeman not installed — install with: gem install brakeman"
  fi
  which semgrep 2>/dev/null && semgrep --config=p/ruby --json --output=/tmp/semgrep-rb.json . 2>/dev/null || true
fi
```

---

## Phase 4 — SCA (Software Composition Analysis / Dependency Audit)

Check all direct and transitive dependencies for known CVEs.

### Node.js
```bash
if [ -f package-lock.json ]; then
  npm audit --json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
vulns = d.get('vulnerabilities', {})
by_sev = {'critical': [], 'high': [], 'moderate': [], 'low': []}
for name, v in vulns.items():
    sev = v.get('severity', 'low')
    if sev in by_sev:
        via = v.get('via', [{}])
        title = via[0] if isinstance(via[0], str) else via[0].get('title', 'transitive')
        by_sev[sev].append(f'{name} ({title})')
for sev in ['critical','high','moderate']:
    if by_sev[sev]:
        print(f'{sev.upper()} ({len(by_sev[sev])}): {chr(10).join(by_sev[sev][:10])}')
" || npm audit 2>/dev/null || true
elif [ -f yarn.lock ]; then
  yarn audit --json 2>/dev/null | head -50 || true
elif [ -f pnpm-lock.yaml ]; then
  pnpm audit 2>/dev/null || true
fi
```

### Python
```bash
if [ -f requirements.txt ] || [ -f pyproject.toml ]; then
  if which pip-audit 2>/dev/null; then
    pip-audit --format json 2>/dev/null | python3 -c "
import json, sys
results = json.load(sys.stdin)
vulns = [r for r in results if r.get('vulns')]
print(f'pip-audit: {len(vulns)} package(s) with vulnerabilities')
for r in vulns:
    for v in r['vulns']:
        print(f'  {r[\"name\"]}=={r[\"version\"]}: {v[\"id\"]} — {v[\"description\"][:80]}')
        print(f'    Fix: upgrade to {v.get(\"fix_versions\", [\"no fix available\"])}')
    " || pip-audit 2>/dev/null
  elif which safety 2>/dev/null; then
    safety check --json 2>/dev/null | python3 -c "
import json, sys
results = json.load(sys.stdin)
for r in results:
    print(f'  {r[0]}=={r[2]}: {r[3][:80]}')
    " || safety check 2>/dev/null
  else
    echo "pip-audit not installed — install with: pip install pip-audit"
  fi
fi
```

### Go
```bash
[ -f go.mod ] && which govulncheck 2>/dev/null && govulncheck ./... 2>/dev/null || true
```

### Ruby
```bash
if [ -f Gemfile.lock ]; then
  if which bundler-audit 2>/dev/null; then
    bundle-audit check --update 2>/dev/null
  else
    echo "bundler-audit not installed — install with: gem install bundler-audit"
  fi
fi
```

### Java
```bash
if [ -f pom.xml ]; then
  which mvn 2>/dev/null && \
    mvn org.owasp:dependency-check-maven:check -DfailBuildOnCVSS=7 2>/dev/null | \
    grep -E "Vulnerability|CVE-" | head -20 || true
fi
```

---

## Phase 5 — Configuration Review

Run for all projects regardless of stack.

```bash
# Dockerfile security
if [ -f Dockerfile ]; then
  echo "=== Dockerfile review ==="
  grep -n "USER root" Dockerfile && echo "  WARNING: Running as root" || true
  grep -n "ADD http" Dockerfile && echo "  WARNING: ADD from URL — use COPY + curl with checksum instead" || true
  grep -n "chmod 777\|chmod -R 777" Dockerfile && echo "  WARNING: World-writable permissions" || true
  grep -n "COPY \. \." Dockerfile && echo "  INFO: Copying full context — ensure .dockerignore excludes secrets" || true
  [ ! -f .dockerignore ] && echo "  WARNING: No .dockerignore found — .env and secrets may be in image" || true
fi

# CORS misconfiguration
echo "=== CORS check ==="
grep -rn --include="*.js" --include="*.ts" --include="*.py" --include="*.go" \
  --include="*.java" --include="*.rb" \
  -E "Access-Control-Allow-Origin.*['\"]?\*['\"]?" . 2>/dev/null | \
  grep -v "test\|spec\|mock" | head -10 && \
  echo "  WARNING: Wildcard CORS — restrict to known origins" || true

# Debug mode in production code
echo "=== Debug flags ==="
grep -rn --include="*.py" -E "^DEBUG\s*=\s*True" . 2>/dev/null | grep -v "test\|example" || true
grep -rn --include="*.js" --include="*.ts" -E "NODE_ENV.*development|debug.*true" \
  . 2>/dev/null | grep -v "test\|example\|.env.example" | head -5 || true

# Insecure session/cookie configuration
echo "=== Cookie/session security ==="
grep -rn --include="*.js" --include="*.ts" --include="*.py" \
  -E "httpOnly\s*:\s*false|secure\s*:\s*false|sameSite\s*:\s*['\"]none['\"]" \
  . 2>/dev/null | grep -v "test\|spec" || true

# SQL injection via string concatenation
echo "=== SQL injection risk ==="
grep -rn --include="*.py" --include="*.js" --include="*.ts" --include="*.java" \
  -E "execute\s*\(\s*[\"'].*\%[sd].*[\"']\s*%|query\s*=.*\+.*req\.|WHERE.*\+\s*(req|request|params|body|query)" \
  . 2>/dev/null | grep -v "test\|spec" | head -10 || true

# Insecure cryptography
echo "=== Weak cryptography ==="
grep -rn --include="*.py" --include="*.js" --include="*.ts" \
  -E "md5\(|sha1\(|DES\.|3DES\.|RC4|createCipher\b" \
  . 2>/dev/null | grep -v "test\|spec\|comment" | head -10 || true

# Hardcoded IPs / internal infrastructure
echo "=== Hardcoded infrastructure ==="
grep -rn --include="*.js" --include="*.ts" --include="*.py" --include="*.go" \
  --include="*.java" --include="*.yml" --include="*.yaml" \
  -E "([0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{2,5}|localhost:[0-9]{4,5}" \
  . 2>/dev/null | grep -v "test\|spec\|mock\|127\.0\.0\.1:.*test" | head -10 || true
```

---

## Phase 6 — DAST (Dynamic Application Security Testing)

Only if a local server is detected. Skip gracefully if no server is running.

```bash
# Detect running services
LOCAL_PORTS=""
for port in 3000 3001 4000 5000 8000 8080 8443 9000; do
  nc -z -w1 localhost $port 2>/dev/null && LOCAL_PORTS="$LOCAL_PORTS $port"
done

if [ -z "$LOCAL_PORTS" ]; then
  echo "No local server detected — skipping DAST. Start the app and re-run to include dynamic tests."
else
  echo "Detected local services on ports:$LOCAL_PORTS"
  TARGET_PORT=$(echo $LOCAL_PORTS | tr ' ' '\n' | head -1)
  TARGET="http://localhost:$TARGET_PORT"
  echo "Running DAST against $TARGET"

  # Security headers check (always available)
  echo "=== Security headers ==="
  curl -sI "$TARGET" 2>/dev/null | grep -iE \
    "content-security-policy|x-content-type-options|x-frame-options|strict-transport-security|permissions-policy" || \
    echo "WARNING: One or more critical security headers missing"
  # Report which are missing:
  HEADERS=$(curl -sI "$TARGET" 2>/dev/null)
  echo "$HEADERS" | grep -qi "x-content-type-options" || echo "  MISSING: X-Content-Type-Options: nosniff"
  echo "$HEADERS" | grep -qi "x-frame-options" || echo "  MISSING: X-Frame-Options: DENY"
  echo "$HEADERS" | grep -qi "content-security-policy" || echo "  MISSING: Content-Security-Policy"
  echo "$HEADERS" | grep -qi "strict-transport-security" || echo "  MISSING: Strict-Transport-Security"

  # Path traversal probe
  echo "=== Path traversal probe ==="
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$TARGET/../../../etc/passwd" 2>/dev/null)
  [ "$STATUS" = "200" ] && echo "CRITICAL: Possible path traversal at $TARGET/../../../etc/passwd" || true

  # Exposed debug/admin endpoints
  echo "=== Exposed debug endpoints ==="
  for endpoint in /debug /console /actuator /actuator/env /actuator/heapdump \
                  /metrics /health/details /swagger-ui /api-docs /graphql/playground \
                  /__debug__ /admin /phpinfo.php; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$TARGET$endpoint" 2>/dev/null)
    [ "$STATUS" = "200" ] && echo "  WARNING: $endpoint returned 200 — verify this should be public" || true
  done

  # Error message leakage
  echo "=== Error leakage ==="
  RESP=$(curl -s "$TARGET/this-path-does-not-exist-appsec-probe-$(date +%s)" 2>/dev/null)
  echo "$RESP" | grep -iE "traceback|stack trace|Exception in|at line [0-9]|Error:.*\.py|\.js:[0-9]" && \
    echo "  WARNING: Stack trace visible in 404 response — disable debug mode" || true

  # NIKTO (if available)
  if which nikto 2>/dev/null; then
    echo "=== Nikto scan ==="
    nikto -h "$TARGET" -maxtime 60 -Format txt 2>/dev/null | grep -E "OSVDB|WARNING|ERROR" | head -20 || true
  fi
fi
```

---

## Phase 7 — Remediate and Report

After all phases complete, produce a structured report and fix issues.

### Severity Classification

| Severity | Definition | Action |
|---|---|---|
| **Critical** | Secrets in code, SQLi, RCE, auth bypass, CVSS 9-10 | Block commit — fix before anything else |
| **High** | Known CVE CVSS 7-8.9, XSS, insecure deserialization, SAST confirmed | Fix before pushing this PR |
| **Medium** | Missing security headers, weak config, CVSS 4-6.9 | Fix in this PR or file a tracked issue |
| **Low** | Informational, best practice, CVSS < 4 | Note and backlog |

### Report Format

For each finding output:
```
[SEVERITY] <title>
File/URL : <path or endpoint>:<line>
Issue    : <what the vulnerability is — one sentence>
Impact   : <what an attacker could do if exploited>
Fix      : <exact code change, command, or config to apply>
GitLab CI: <which scanner catches this: SAST / Secret Detection / Dependency Scanning / DAST / Container Scanning>
```

### After Applying Fixes

1. Re-run the specific check that flagged the issue to confirm it is resolved.
2. If a finding cannot be fixed immediately (e.g. transitive dependency with no fix version):
   - Add a suppression comment with rationale: `# nosec B324 — MD5 used only for non-security cache key, not cryptographic`
   - File a ticket and note the ticket number in the comment
   - Do NOT suppress without explanation
3. Confirm the overall finding count decreased before handing back to the user.

---

## What NOT to do

- Do not skip Phase 2 (secrets) — run it even if the user only asked for SAST.
- Do not report a finding without a remediation step.
- Do not mark something as a false positive without explaining specifically why.
- Do not suppress warnings with a blanket `# noqa` or `# nosec` without a comment explaining the rationale.
- Do not stop after one tool — run all available tools for the detected stack.
- Do not run `rm`, `DROP TABLE`, or any destructive command as part of scanning.
- Do not send scan results to external services or URLs.

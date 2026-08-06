# appsec-dast-sim

**An OWASP security review of your code, without deploying anything.**

Real DAST needs a running application, a deployed target, and a scanner that fires live
requests at it. That doesn't fit into "I'm about to open an MR." This skill gets you most
of the value earlier: it reads your source, walks the full
[OWASP Web Security Testing Guide v4.2](reference/wstg-v42-checklist.md) checklist, and
reports what a DAST run *would* find — with the exact `curl` you'd use to confirm it.

```
You: /appsec-dast-sim
```

No containers. No credentials. No running app. Nothing leaves your machine.

---

## When to use this

**Good fit:**
- Designing or reviewing an API before it's deployed anywhere
- Pre-MR check on auth, session handling, or input validation changes
- You want an OWASP-shaped review and don't have a DAST environment
- Onboarding onto an unfamiliar service and want its attack surface mapped

**Wrong tool:**
- You need SAST, dependency, secret, or container scanning → use
  [`appsec-scan`](../appsec-scan/README.md)
- You need a real DAST run against a deployed target → use the catalogue's `dast` /
  `api-security` components in CI
- You want general code review or linting → this is not that

---

## What it actually does

1. **Maps your attack surface.** Finds every route, endpoint, handler, and entry point —
   controllers, route tables, serverless handlers, GraphQL schemas.
2. **Walks the WSTG v4.2 checklist**, ten categories:

   | Category | Covers |
   |---|---|
   | `WSTG-CONF` | Configuration and deployment |
   | `WSTG-AUTHN` | Authentication |
   | `WSTG-AUTHZ` | Authorization |
   | `WSTG-SESS` | Session management |
   | `WSTG-INPV` | Input validation — SQLi, XSS, command injection, SSRF, XXE |
   | `WSTG-ERRH` | Error handling and information leakage |
   | `WSTG-CRYP` | Cryptography |
   | `WSTG-BUSL` | Business logic |
   | `WSTG-APIT` | REST and GraphQL API testing |

3. **Reads the code behind each test** — auth middleware, input handling, session
   config, ORM calls — rather than pattern-matching for scary-looking strings.
4. **Reports findings by severity**, each one citing the file and line.

### What a finding looks like

```
[WSTG-AUTHN-04] Missing auth middleware on protected route
Severity: CRITICAL
File: src/routes/admin.ts:42
Endpoint: GET /admin/users
Issue: Route handler is missing authentication middleware. Any unauthenticated
       user can access the admin user list.
Probe: curl -X GET http://localhost:3000/admin/users
Remediation: Add auth middleware before the handler:
       router.get('/admin/users', authenticate, authorize('admin'), handler)
```

Findings are ordered CRITICAL → HIGH → MEDIUM → LOW, followed by a coverage table
showing every WSTG ID as PASS, FAIL, or SKIP with a reason. A test is marked SKIP when
your code has no relevant surface — no GraphQL endpoint means `WSTG-APIT-01` is skipped,
not silently dropped.

---

## Ground rules it follows

These are enforced in the skill and worth knowing, because they define what you can
trust:

- **No live attacks.** It never sends a request anywhere. Probes are generated for *you*
  to run against your own environment.
- **Every finding cites file and line.** No "consider reviewing your auth" hand-waving.
- **No theoretical findings.** If it can't point at the code pattern, it doesn't report it.
- **Framework defaults are respected.** It won't flag CSRF protection as missing when
  your framework enables it by default.
- **Skips are declared.** A test that didn't apply shows up as SKIP with a reason, never
  as a pass.

---

## Honest limitations

This is static reasoning about dynamic behaviour. It **cannot** see:

- Runtime configuration — env vars, secrets managers, feature flags, sidecars
- Reverse proxy, WAF, service mesh, or API gateway rules applied in front of your app
- Anything injected at deploy time rather than written in the repo
- Whether a probe *actually* succeeds — that's what the `curl` commands are for

Treat the output as a prioritised list of things to verify, not a pass/fail gate. A clean
report means "nothing visible in the source," not "not exploitable."

---

## Using it with `appsec-scan`

They cover different ground and compose well:

| | `appsec-scan` | `appsec-dast-sim` |
|---|---|---|
| Finds | Known-vulnerable deps, secrets, CVEs, SAST patterns | Design and logic flaws, missing authz, unsafe input handling |
| Needs | Docker + scanner images | Nothing |
| Runtime | Minutes | Seconds to minutes |
| Output | `.appsec-results/` + `TRIAGE.md` | A report in the conversation |
| Gate | Severity gate, coverage-aware | Advisory only |

A reasonable habit: `/appsec-dast-sim` while designing or reviewing an endpoint,
`/appsec-scan` before you push.

---

## Reference

The vendored WSTG v4.2 checklist is at
[`reference/wstg-v42-checklist.md`](reference/wstg-v42-checklist.md) — it works fully
offline and is what the skill walks through.

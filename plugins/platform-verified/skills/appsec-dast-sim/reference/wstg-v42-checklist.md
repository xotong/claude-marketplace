# OWASP Web Security Testing Guide v4.2 — Quick Reference

Condensed checklist of all test IDs, names, and one-line descriptions.
Vendored locally for airgap compliance. Source: OWASP WSTG v4.2 (2021).
Full guide: https://owasp.org/www-project-web-security-testing-guide/ (requires internet)

---

## WSTG-INFO — Information Gathering

| ID | Test Name | Description |
|---|---|---|
| WSTG-INFO-01 | Conduct Search Engine Discovery Reconnaissance | Use search engines to find exposed files, directories, and sensitive data |
| WSTG-INFO-02 | Fingerprint Web Server | Identify web server type and version from headers, error pages, and behavior |
| WSTG-INFO-03 | Review Webserver Metafiles for Information Leakage | Check robots.txt, sitemap.xml, and .well-known for sensitive paths |
| WSTG-INFO-04 | Enumerate Application on Webserver | Discover all applications hosted on the same server |
| WSTG-INFO-05 | Review Web Page Content for Information Leakage | Find comments, metadata, and embedded credentials in HTML/JS |
| WSTG-INFO-06 | Identify Application Entry Points | Map all input vectors: forms, headers, cookies, query params |
| WSTG-INFO-07 | Map Execution Paths Through Application | Trace all code paths and workflow transitions |
| WSTG-INFO-08 | Fingerprint Web Application Framework | Identify framework/version from headers, cookies, file extensions |
| WSTG-INFO-09 | Fingerprint Web Application | Identify the application and version |
| WSTG-INFO-10 | Map Application Architecture | Discover reverse proxies, load balancers, CDN, WAF in path |

---

## WSTG-CONF — Configuration and Deployment Management

| ID | Test Name | Description |
|---|---|---|
| WSTG-CONF-01 | Test Network Infrastructure Configuration | Check for exposed debug/admin endpoints not guarded in production |
| WSTG-CONF-02 | Test Application Platform Configuration | Check framework debug flags, verbose error modes, stack traces in responses |
| WSTG-CONF-03 | Test File Extension Handling for Sensitive Information | Verify sensitive extensions (.bak, .log, .config) are not served |
| WSTG-CONF-04 | Review Old Backup and Unreferenced Files for Sensitive Information | Find forgotten backup files in web root |
| WSTG-CONF-05 | Enumerate Infrastructure and Application Admin Interfaces | Check for TRACE/OPTIONS and unnecessary HTTP methods on endpoints |
| WSTG-CONF-06 | Test HTTP Methods | Verify only required HTTP methods are accepted; disable TRACE |
| WSTG-CONF-07 | Test HTTP Strict Transport Security | Check HSTS header: max-age ≥ 31536000, includeSubDomains |
| WSTG-CONF-08 | Test RIA Cross Domain Policy | Check CORS: no wildcard+credentials, no reflected Origin without allowlist |
| WSTG-CONF-09 | Test File Permission | Verify filesystem permissions on server-side files |
| WSTG-CONF-10 | Test for Subdomain Takeover | Check DNS CNAMEs pointing to unclaimed cloud resources |
| WSTG-CONF-11 | Test Cloud Storage | Check for public S3/GCS buckets and exposed storage keys in code |

Note: WSTG-CONF-10 in WSTG v4.2 is "Subdomain Takeover" but the appsec-dast-sim skill uses CONF-10 to mean file upload (mapping from earlier WSTG numbering used by the CI components). Always verify test ID mapping against the specific WSTG version in use.

---

## WSTG-IDNT — Identity Management

| ID | Test Name | Description |
|---|---|---|
| WSTG-IDNT-01 | Test Role Definitions | Verify all roles are clearly defined and enforced |
| WSTG-IDNT-02 | Test User Registration Process | Check for weak identity proofing in self-registration |
| WSTG-IDNT-03 | Test Account Provisioning Process | Verify proper approval workflow for account creation |
| WSTG-IDNT-04 | Testing for Account Enumeration and Guessable User Account | Check if login errors differentiate between bad user vs. bad password |
| WSTG-IDNT-05 | Testing for Weak or Unenforced Username Policy | Verify username constraints prevent spoofing |

---

## WSTG-AUTHN — Authentication

| ID | Test Name | Description |
|---|---|---|
| WSTG-AUTHN-01 | Testing for Credentials Transported over an Encrypted Channel | Auth endpoints must use HTTPS; no auth over plain HTTP |
| WSTG-AUTHN-02 | Testing for Default Credentials | Check for hardcoded admin/admin, test/test, or default API keys |
| WSTG-AUTHN-03 | Testing for Weak Lock Out Mechanism | Verify brute force protection: rate limiting or lockout after N failures |
| WSTG-AUTHN-04 | Testing for Bypassing Authentication Schema | Verify all protected routes require authentication middleware |
| WSTG-AUTHN-05 | Testing for Vulnerable Remember Password | Check "remember me" token security: entropy, expiry, single-use |
| WSTG-AUTHN-06 | Testing for Browser Cache Weaknesses | Verify sensitive pages use Cache-Control: no-store |
| WSTG-AUTHN-07 | Testing for Weak Password Policy | Verify minimum length and complexity enforced server-side |
| WSTG-AUTHN-08 | Testing for Weak Security Question/Answer | Check if password reset relies on guessable security questions |
| WSTG-AUTHN-09 | Testing for Weak Password Change or Reset Functionalities | Verify reset tokens: crypto-random, expiry set, single-use |
| WSTG-AUTHN-10 | Testing for Weaker Authentication in Alternative Channel | Verify mobile/API/webhook endpoints enforce same auth as web |

Note: WSTG-AUTHN-06 in the skill maps to "Weak Password Policy" (v4.1 numbering); WSTG-AUTHN-07 maps to "Weak Password Reset". WSTG v4.2 renumbered some tests — use test names as the primary identifier.

---

## WSTG-AUTHZ — Authorization

| ID | Test Name | Description |
|---|---|---|
| WSTG-AUTHZ-01 | Testing Directory Traversal / File Include | Check path params and file=, path= query params for ../ traversal |
| WSTG-AUTHZ-02 | Testing for Bypassing Authorization Schema | Verify ownership checks — accessing other users' resources by changing IDs |
| WSTG-AUTHZ-03 | Testing for Privilege Escalation | Check role not taken from client request; no horizontal→vertical escalation |
| WSTG-AUTHZ-04 | Testing for Insecure Direct Object References | Sequential/guessable IDs with no ownership verification = IDOR |

---

## WSTG-SESS — Session Management

| ID | Test Name | Description |
|---|---|---|
| WSTG-SESS-01 | Testing for Session Management Schema | Check JWT secret strength, token entropy, alg:none acceptance |
| WSTG-SESS-02 | Testing for Cookies Attributes | Verify HttpOnly, Secure, SameSite on all session/auth cookies |
| WSTG-SESS-03 | Testing for Session Fixation | Session ID regenerated after login to prevent fixation attack |
| WSTG-SESS-04 | Testing for Exposed Session Variables | Session tokens must not appear in URLs, logs, or error responses |
| WSTG-SESS-05 | Testing for Cross Site Request Forgery | CSRF token or SameSite cookie required on all state-changing requests |
| WSTG-SESS-06 | Testing for Logout Functionality | Session invalidated server-side on logout; token expiry enforced |
| WSTG-SESS-07 | Testing Session Timeout | Idle timeout and absolute expiry configured for tokens/sessions |
| WSTG-SESS-08 | Testing for Session Puzzling | Same session variable not reused across different authentication flows |
| WSTG-SESS-09 | Testing for Session Hijacking | Session tokens not predictable or guessable via analysis |

---

## WSTG-INPV — Input Validation

| ID | Test Name | Description |
|---|---|---|
| WSTG-INPV-01 | Testing for Reflected Cross Site Scripting | User input rendered in HTML without encoding in same response |
| WSTG-INPV-02 | Testing for Stored Cross Site Scripting | User input stored and rendered later without sanitization |
| WSTG-INPV-03 | Testing for HTTP Verb Tampering | Unexpected HTTP methods bypass access controls |
| WSTG-INPV-04 | Testing for HTTP Parameter Pollution | Duplicate parameters with conflicting values bypass validation |
| WSTG-INPV-05 | Testing for SQL Injection | String concatenation in SQL queries instead of parameterized statements |
| WSTG-INPV-06 | Testing for LDAP Injection | LDAP filter construction with unsanitized user input |
| WSTG-INPV-07 | Testing for XML Injection | XML/XXE: external entity processing not disabled on user-supplied XML |
| WSTG-INPV-08 | Testing for SSI Injection | Server-side includes or template evaluation of user input |
| WSTG-INPV-09 | Testing for XPath Injection | XPath filter constructed with user input concatenated |
| WSTG-INPV-10 | Testing for IMAP/SMTP Injection | Email header fields (To, CC, Subject) constructed from user input |
| WSTG-INPV-11 | Testing for Code Injection | eval(), exec(), new Function() with user-controlled input |
| WSTG-INPV-12 | Testing for Command Injection | Shell commands constructed with user input (exec, system, popen) |
| WSTG-INPV-13 | Testing for Format String Injection | User input used as format string in printf-style functions |
| WSTG-INPV-14 | Testing for Incubated Vulnerability | Stored payloads that execute in a different context later |
| WSTG-INPV-15 | Testing for HTTP Splitting/Smuggling | CRLF in redirects or headers allows response splitting |
| WSTG-INPV-16 | Testing for HTTP Incoming Requests | Verify request smuggling mitigations between proxy and backend |
| WSTG-INPV-17 | Testing for Host Header Injection | Host header used for redirect or link generation without validation |
| WSTG-INPV-18 | Testing for Server Side Template Injection | Template engine processes user input as template syntax |
| WSTG-INPV-19 | Testing for Server-Side Request Forgery | User-supplied URLs fetched server-side without allowlist validation |

Note: The skill uses a simplified numbering derived from the CI components' test mapping. WSTG-INPV-17 in the skill = HTTP Splitting; WSTG-INPV-18 = Open Redirect; WSTG-INPV-19 = JWT Attacks. The v4.2 canonical numbering differs (as shown above). Use test names as the definitive identifier.

---

## WSTG-ERRH — Error Handling

| ID | Test Name | Description |
|---|---|---|
| WSTG-ERRH-01 | Testing for Improper Error Handling | Stack traces, DB errors, internal paths exposed in HTTP error responses |
| WSTG-ERRH-02 | Testing for Stack Traces | Verbose error mode enabled in production config |

---

## WSTG-CRYP — Cryptography

| ID | Test Name | Description |
|---|---|---|
| WSTG-CRYP-01 | Testing for Weak Transport Layer Security | SSLv3/TLS 1.0/1.1 or weak ciphers (RC4, DES) enabled |
| WSTG-CRYP-02 | Testing for Padding Oracle | CBC mode with distinguishable padding errors enables oracle attack |
| WSTG-CRYP-03 | Testing for Sensitive Information Sent via Unencrypted Channels | PII stored or transmitted in plaintext |
| WSTG-CRYP-04 | Testing for Weak Encryption | Math.random() / random.random() used for security tokens instead of CSPRNG |

---

## WSTG-BUSLOGIC — Business Logic

| ID | Test Name | Description |
|---|---|---|
| WSTG-BUSL-01 | Test Business Logic Data Validation | Negative quantities, zero/negative prices, integer overflow in business fields |
| WSTG-BUSL-02 | Test Ability to Forge Requests | Attacker forges request to trigger unintended state transitions |
| WSTG-BUSL-03 | Test Integrity Checks | Hidden fields or client-supplied values (price, discount) trusted server-side |
| WSTG-BUSL-04 | Test for Process Timing | Race conditions in concurrent requests (TOCTOU, double-spend) |
| WSTG-BUSL-05 | Test Number of Times a Function Can Be Used Limits | No limit on referral/coupon redemptions or password reset link reuse |
| WSTG-BUSL-06 | Testing for the Circumvention of Work Flows | Multi-step flows that can be bypassed by skipping required steps |
| WSTG-BUSL-07 | Test Defenses Against Application Misuse | No rate limiting on high-value actions (signup, payment, search) |
| WSTG-BUSL-08 | Test Upload of Unexpected File Types | Polyglot files, zip bombs, SVG with scripts accepted by upload endpoints |
| WSTG-BUSL-09 | Test Upload of Malicious Files | Malware and web shells accepted by upload endpoints |

---

## WSTG-APIT — API Testing

| ID | Test Name | Description |
|---|---|---|
| WSTG-APIT-01 | Testing GraphQL | Introspection in prod, no depth/complexity limit, N+1 DoS, batch query abuse |
| WSTG-APIT-02 | Testing REST | Mass assignment, verb tampering, insecure direct object exposure |
| WSTG-APIT-03 | Testing Web Sockets | WebSocket auth, message validation, cross-site WebSocket hijacking |

---

## Severity mapping guide

| Severity | Meaning |
|---|---|
| CRITICAL | Direct exploit path with high impact; must fix before any release |
| HIGH | Significant risk; exploit likely given motivation; fix within sprint |
| MEDIUM | Notable risk; requires specific conditions or chaining; fix in next release |
| LOW | Defense-in-depth issue; minimal direct impact; fix as capacity allows |
| INFO | Observation with no direct security impact; consider for hardening |

---

*Source: OWASP Web Security Testing Guide v4.2 (2021). OWASP is a registered trademark of the OWASP Foundation, Inc. This checklist is a condensed quick reference for internal use; it does not replace the full WSTG guide.*

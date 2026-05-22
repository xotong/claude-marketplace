---
name: api-design-principles
description: >
  Automatically applied when designing or reviewing REST or GraphQL API endpoints.
  Enforces naming conventions, HTTP semantics, status codes, versioning, pagination,
  error response format (RFC 7807), and security headers.
  Activate when the user: designs a new API endpoint, reviews an existing one,
  asks about REST conventions, says "design this API", "review my endpoints",
  "add a new route", "create an API for X", "what status code should I return",
  "how should I version my API", "API design review", "check my REST API".
  Do NOT activate for non-API code, frontend, or database schema work.
---

# API Design Principles

Apply these standards whenever creating or reviewing REST or GraphQL API endpoints.
Check against each section relevant to the current work.

## REST Conventions

### Resource Naming
- Use plural nouns for collections: `/users`, `/orders`, `/products`
- Use kebab-case for multi-word resources: `/user-profiles`, `/order-items`
- Never use verbs in URLs: `/getUser` → `/users/{id}` (GET)
- Nest resources to show ownership: `/users/{id}/orders`, `/orders/{id}/items`
- Maximum nesting depth: 2 levels. Deeper = design smell, flatten with query params

### HTTP Methods
| Action | Method | Example |
|---|---|---|
| List collection | GET | GET /users |
| Get single resource | GET | GET /users/{id} |
| Create | POST | POST /users |
| Full replace | PUT | PUT /users/{id} |
| Partial update | PATCH | PATCH /users/{id} |
| Delete | DELETE | DELETE /users/{id} |
| Never use GET for mutations | — | Never GET /users/delete |

### Status Codes
Use the most specific appropriate code:
- `200 OK` — successful GET, PUT, PATCH, DELETE with body
- `201 Created` — successful POST; include `Location` header pointing to new resource
- `204 No Content` — successful DELETE or action with no response body
- `400 Bad Request` — invalid input (malformed JSON, failed validation)
- `401 Unauthorized` — missing or invalid authentication
- `403 Forbidden` — authenticated but not authorised for this resource
- `404 Not Found` — resource does not exist (never leak whether it existed before)
- `409 Conflict` — duplicate resource, optimistic lock failure
- `422 Unprocessable Entity` — syntactically valid but semantically invalid
- `429 Too Many Requests` — rate limit exceeded; include `Retry-After` header
- `500 Internal Server Error` — unexpected server fault (never expose stack traces)

**Never:** return 200 with `{"success": false}`. Use the correct 4xx/5xx code.

### Error Response Format (RFC 7807)
All errors must use Problem Details JSON:
```json
{
  "type": "https://api.example.gov.sg/problems/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "The 'email' field must be a valid email address.",
  "instance": "/users/register",
  "errors": [
    { "field": "email", "code": "INVALID_FORMAT", "message": "Must be a valid email" }
  ]
}
```
Content-Type must be `application/problem+json`.
Never expose stack traces, internal IDs, or database error messages in responses.

---

## API Versioning

- Version in the URL path: `/v1/users`, `/v2/orders`
- Never break a published version — add a new version instead
- Support the previous major version for at least 6 months after a new version ships
- Communicate deprecation via `Deprecation` and `Sunset` response headers:
  ```
  Deprecation: Sun, 01 Jun 2026 00:00:00 GMT
  Sunset: Sun, 01 Dec 2026 00:00:00 GMT
  Link: <https://api.example.gov.sg/v2/users>; rel="successor-version"
  ```

---

## Pagination

All list endpoints that could return more than ~20 items must be paginated.

**Preferred: cursor-based** (for large/live datasets)
```json
{
  "data": [...],
  "pagination": {
    "next_cursor": "eyJpZCI6MTAwfQ==",
    "prev_cursor": "eyJpZCI6NTB9",
    "has_next": true,
    "has_prev": true,
    "limit": 20
  }
}
```

**Acceptable: offset-based** (for small, stable datasets with UI page controls)
```json
{
  "data": [...],
  "pagination": {
    "page": 2,
    "per_page": 20,
    "total": 143,
    "total_pages": 8
  }
}
```

Query params: `?limit=20&cursor=...` or `?page=2&per_page=20`.
Default and maximum limits must be documented and enforced server-side.

---

## Security Requirements

Every API endpoint must have:

1. **Authentication check** — return 401 if missing/invalid token
2. **Authorisation check** — verify the caller owns/can access the resource; return 403 if not
3. **Input validation** — validate all path params, query params, and body fields; return 400/422 with field-level errors
4. **Rate limiting** — protect all endpoints; include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
5. **Response headers:**
   ```
   Content-Type: application/json
   X-Content-Type-Options: nosniff
   X-Frame-Options: DENY
   Cache-Control: no-store  (for any endpoint returning personal data)
   ```
6. **No sensitive data in URLs** — tokens, passwords, and PII must go in headers or request body, never in query strings (they appear in server logs)

---

## Review Checklist

When reviewing an existing endpoint, check each item:

- [ ] URL uses plural nouns, kebab-case, no verbs
- [ ] HTTP method matches the action semantics
- [ ] Correct status code returned for success and each error case
- [ ] Errors use RFC 7807 Problem Details format
- [ ] Versioned at `/vN/`
- [ ] List endpoint is paginated with consistent envelope
- [ ] Auth + authz checked before any business logic
- [ ] Input validation with field-level error messages
- [ ] No stack traces or internal errors in responses
- [ ] Rate limiting applied
- [ ] Security headers present in responses

---

## GraphQL-Specific Rules

- All mutations must require authentication
- Use query depth limiting to prevent DoS via deeply nested queries (max depth: 10)
- Use query complexity analysis — reject queries above a complexity budget
- Never expose `__schema` introspection in production (disable or restrict to internal IPs)
- Errors must still follow a consistent structure: `{ "errors": [{ "message": "...", "extensions": { "code": "..." } }] }`
- Use DataLoader pattern for all N+1 query risks

## What NOT to do

- Do not design endpoints that break REST semantics to match database table structure
- Do not return 200 for errors
- Do not put business logic in URL paths (verbs like `/processOrder`)
- Do not skip pagination on list endpoints
- Do not expose internal implementation details in error messages

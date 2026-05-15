---
name: openapi-spec-generation
description: >
  Generate or update the OpenAPI (Swagger) specification when API routes are
  created or modified. Keeps the spec in sync with the implementation.
  Activate when: API routes change, the user says "update the spec",
  "generate OpenAPI", "update swagger", "sync the API docs", "generate API docs",
  "create openapi.yaml", "document this endpoint", "add this route to the spec",
  "openapi-spec-generation", "the spec is out of date".
  Do NOT activate for non-API changes, frontend, or database work.
---

# OpenAPI Spec Generation

Keep the OpenAPI 3.1 specification in sync with the implementation every time
API routes are added or modified.

## Step 1 — Locate or Initialise the Spec

```bash
# Look for an existing spec
find . -maxdepth 4 -name "openapi.yaml" -o -name "openapi.json" \
  -o -name "swagger.yaml" -o -name "swagger.json" \
  -o -name "api-spec.yaml" 2>/dev/null | head -5
```

If no spec exists, create `openapi.yaml` at the repo root with this skeleton:

```yaml
openapi: "3.1.0"
info:
  title: "<Service Name> API"
  version: "1.0.0"
  description: >
    <One paragraph describing the service and who consumes this API.>
  contact:
    name: "<Team Name>"
    email: "<team@example.gov.sg>"
servers:
  - url: "https://api.example.gov.sg/v1"
    description: Production
  - url: "https://staging-api.example.gov.sg/v1"
    description: Staging
  - url: "http://localhost:8080/v1"
    description: Local development
tags: []
paths: {}
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
security:
  - BearerAuth: []
```

## Step 2 — Check for Auto-Generation Tools

Try framework-native spec generation before writing YAML manually.

### Node.js / Express (tsoa, swagger-jsdoc)
```bash
if [ -f package.json ]; then
  # tsoa
  which tsoa 2>/dev/null && tsoa spec 2>/dev/null && echo "tsoa: spec generated" || true
  # swagger-jsdoc
  which swagger-jsdoc 2>/dev/null && swagger-jsdoc -d swaggerDef.js "**/*.js" \
    -o openapi.json 2>/dev/null || true
fi
```

### Python / FastAPI
```bash
# FastAPI auto-generates at /openapi.json when server is running
if grep -r "from fastapi\|import fastapi" . --include="*.py" -l 2>/dev/null | grep -q .; then
  echo "FastAPI detected — spec available at http://localhost:8000/openapi.json when server is running"
  # Export if server is running
  curl -s http://localhost:8000/openapi.json 2>/dev/null | python3 -m json.tool > /tmp/openapi-fastapi.json && \
    echo "Fetched FastAPI spec" || true
fi
```

### Python / Django REST Framework (drf-spectacular)
```bash
if which python 2>/dev/null && grep -r "drf_spectacular\|rest_framework" . --include="*.py" -l 2>/dev/null | grep -q .; then
  python manage.py spectacular --file openapi.yaml 2>/dev/null && echo "drf-spectacular: spec generated" || true
fi
```

### Spring Boot
```bash
if [ -f pom.xml ] && grep -q "springdoc\|springfox" pom.xml 2>/dev/null; then
  echo "Spring OpenAPI detected — spec available at http://localhost:8080/v3/api-docs when server is running"
fi
```

### Go (swaggo)
```bash
if [ -f go.mod ] && which swag 2>/dev/null; then
  swag init 2>/dev/null && echo "swaggo: spec generated at docs/swagger.yaml" || true
fi
```

## Step 3 — Update the Spec for Changed Endpoints

For each API endpoint that was added or modified, add or update the corresponding
path entry in `openapi.yaml`. Use this structure:

```yaml
paths:
  /users/{id}:
    get:
      summary: Get a user by ID
      operationId: getUserById
      tags: [Users]
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
          description: The user's unique identifier
      responses:
        "200":
          description: User found
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/User"
        "401":
          $ref: "#/components/responses/Unauthorized"
        "403":
          $ref: "#/components/responses/Forbidden"
        "404":
          $ref: "#/components/responses/NotFound"
      security:
        - BearerAuth: []

components:
  responses:
    Unauthorized:
      description: Authentication required
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/ProblemDetail"
    Forbidden:
      description: Insufficient permissions
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/ProblemDetail"
    NotFound:
      description: Resource not found
      content:
        application/problem+json:
          schema:
            $ref: "#/components/schemas/ProblemDetail"

  schemas:
    ProblemDetail:
      type: object
      required: [type, title, status]
      properties:
        type:
          type: string
          format: uri
        title:
          type: string
        status:
          type: integer
        detail:
          type: string
        instance:
          type: string
          format: uri
```

## Step 4 — Add Reusable Components

Extract repeated schemas into `components/schemas` rather than inlining them everywhere:

```yaml
components:
  schemas:
    PaginatedResponse:
      type: object
      required: [data, pagination]
      properties:
        data:
          type: array
          items: {}
        pagination:
          type: object
          required: [next_cursor, has_next, limit]
          properties:
            next_cursor:
              type: string
              nullable: true
            prev_cursor:
              type: string
              nullable: true
            has_next:
              type: boolean
            has_prev:
              type: boolean
            limit:
              type: integer
```

## Step 5 — Validate the Spec

```bash
# Validate with swagger-cli or redocly
if which swagger-cli 2>/dev/null; then
  swagger-cli validate openapi.yaml && echo "openapi.yaml: valid" || echo "openapi.yaml: INVALID"
elif which npx 2>/dev/null; then
  npx @redocly/cli lint openapi.yaml 2>/dev/null || \
  npx swagger-cli validate openapi.yaml 2>/dev/null || true
fi

# Check for breaking changes if previous version exists in git
if git show HEAD:openapi.yaml 2>/dev/null | grep -q "openapi:"; then
  which oasdiff 2>/dev/null && \
    git show HEAD:openapi.yaml > /tmp/openapi-prev.yaml && \
    oasdiff breaking /tmp/openapi-prev.yaml openapi.yaml 2>/dev/null || true
fi
```

## Step 6 — Confirm Coverage

After updating the spec, verify every route in the codebase is documented:

```bash
# Extract routes from code (Node/Express)
grep -rn "router\.\(get\|post\|put\|patch\|delete\)\|app\.\(get\|post\|put\|patch\|delete\)" \
  --include="*.js" --include="*.ts" . 2>/dev/null | grep -v "test\|spec" | head -30

# Extract paths from spec
grep "^  /" openapi.yaml 2>/dev/null || python3 -c "
import yaml
spec = yaml.safe_load(open('openapi.yaml'))
for path in sorted(spec.get('paths', {}).keys()):
    methods = list(spec['paths'][path].keys())
    print(f'{path}: {methods}')
" 2>/dev/null
```

Flag any route in the code that has no corresponding entry in the spec.

## What NOT to do

- Do not duplicate schema definitions — use `$ref` to `components/schemas`
- Do not leave example values with real credentials or internal URLs
- Do not document internal-only endpoints in the external-facing spec (use a separate spec or `x-internal: true`)
- Do not skip the validation step — an invalid spec breaks API documentation and client SDK generation
- Do not use OpenAPI 2.0 (Swagger) for new specs — use OpenAPI 3.1

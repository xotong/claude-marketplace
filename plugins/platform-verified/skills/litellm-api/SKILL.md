---
name: litellm-api
description: >
  Build, debug, and optimise applications that call the organisation's internal LLM
  gateway (LiteLLM). Use this skill when the user is writing code that calls
  the internal AI API, asks about available models, needs to debug LLM
  integration code, wants to implement streaming or tool use via the gateway,
  asks about rate limits or auth, or is migrating from direct Anthropic SDK
  calls to the internal gateway. Trigger phrases include: "call our LLM",
  "use the internal model", "LiteLLM endpoint", "LITELLM_API_KEY", "internal
  AI gateway", "which models do we have", "how do I use Claude internally".
  Do NOT activate for questions about the public Anthropic API that have
  nothing to do with the internal gateway.
---

# the organisation LiteLLM Gateway — Developer Skill

the organisation runs an internal LiteLLM gateway that proxies requests to the
underlying model provider (currently KimiK2 via vLLM). All internal AI
integrations should use this gateway — never call provider APIs directly.

## Gateway details

| Property | Value |
|---|---|
| Base URL | `https://litellm.company.com/v1` |
| Auth | `LITELLM_API_KEY` — request from the Platform Team or retrieve from Vault |
| Interface | OpenAI-compatible (works with `openai` SDK, LangChain, LlamaIndex, etc.) |
| Default model | `kimi-k2` |

> **[PLACEHOLDER]** Replace URL, model name, and auth source above with your
> actual values.

## Quickstart — Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://litellm.company.com/v1",
    api_key=os.environ["LITELLM_API_KEY"],  # never hardcode
)

response = client.chat.completions.create(
    model="kimi-k2",
    messages=[{"role": "user", "content": "Hello"}],
    temperature=0,
)
print(response.choices[0].message.content)
```

## Streaming

```python
with client.chat.completions.create(
    model="kimi-k2",
    messages=[{"role": "user", "content": "Explain recursion"}],
    stream=True,
) as stream:
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Tool use / function calling

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_ticket",
            "description": "Retrieve a Jira ticket by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "e.g. PLAT-123"}
                },
                "required": ["ticket_id"],
            },
        },
    }
]

response = client.chat.completions.create(
    model="kimi-k2",
    messages=[{"role": "user", "content": "What's the status of PLAT-123?"}],
    tools=tools,
    tool_choice="auto",
)
```

## Structured / JSON output

```python
import json

response = client.chat.completions.create(
    model="kimi-k2",
    messages=[
        {"role": "system", "content": "You are a JSON API. Return only valid JSON."},
        {"role": "user", "content": "Extract name and email from: John Doe <john@example.com>"},
    ],
    response_format={"type": "json_object"},
    temperature=0,
)
result = json.loads(response.choices[0].message.content)
```

## Environment variable setup

```bash
# .env (never commit this file)
LITELLM_API_KEY=your-key-here

# In code — always read from environment
import os
api_key = os.environ["LITELLM_API_KEY"]  # raises KeyError if not set — good
```

Retrieve your key from:
> **[PLACEHOLDER]** Add your internal secret manager / Vault path or instructions
> for requesting a key from the Platform Team.

## Rate limits and quotas

> **[PLACEHOLDER]** Document your rate limits here once established.
> Example: "500 requests/minute per team. Burst to 1000 for 30 seconds.
> Headers: X-RateLimit-Remaining, X-RateLimit-Reset"

Contact `#platform-team` if you need a higher quota for a specific use case.

## Error handling

```python
from openai import APIConnectionError, APIStatusError, RateLimitError
import time

def call_with_retry(client, messages, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(
                model="kimi-k2",
                messages=messages,
                temperature=0,
            )
        except RateLimitError:
            if attempt == max_retries:
                raise
            time.sleep(2 ** attempt)
        except APIStatusError as e:
            if e.status_code >= 500 and attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                raise
```

## What NOT to do

- **Never hardcode `LITELLM_API_KEY`** in source code, config files, or Dockerfiles
- **Never call `api.anthropic.com` directly** — use the gateway so requests are
  logged, rate-limited, and attributed to your team
- **Never log full prompt/response content** to application logs — these may
  contain user PII
- **Never use `temperature > 0`** for structured output or tool use — adds
  non-determinism with no benefit
- Do not create a new `OpenAI` client per request — instantiate once and reuse

## Migrating from direct Anthropic SDK

| Direct Anthropic SDK | Internal gateway (openai SDK) |
|---|---|
| `import anthropic` | `from openai import OpenAI` |
| `base_url` not needed | `base_url="https://litellm.company.com/v1"` |
| `ANTHROPIC_API_KEY` | `LITELLM_API_KEY` |
| `client.messages.create()` | `client.chat.completions.create()` |
| `model="claude-opus-4-7"` | `model="kimi-k2"` |
| `max_tokens=` | `max_tokens=` (same) |

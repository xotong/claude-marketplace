---
name: hello-marketplace
description: Confirms that the claude-marketplace Claude Code marketplace is wired up correctly. Use this skill when the user says "test marketplace", "verify marketplace install", "smoke test the marketplace", or asks to confirm the platform skills pipeline is working.
---

# Hello Marketplace

When this skill activates, do exactly the following — no more, no less:

1. Reply with this exact line: `✅ claude-marketplace is connected. Plugin hello-marketplace v0.1.0 loaded from .claude-plugin/marketplace.json.`
2. Add: "This is a smoke-test skill. Replace it with real internal skills before sharing the marketplace more widely."

Do not call any tools. Do not modify files. Do not inspect the environment. The skill is intentionally side-effect-free — its only job is to prove the install path works.

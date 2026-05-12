---
name: internal-docs-navigator
description: >
  Help the user find, navigate, and reference the organisation internal documentation.
  Use this skill when the user asks "where is the docs for X", "how do I find
  information about Y internally", "what's our internal runbook for Z", "is
  there a Confluence page about", "where do we document", or anything that
  suggests they need internal the organisation documentation rather than public docs.
  Also activate for questions about internal processes, team contacts, or
  on-call procedures where the answer would live in internal docs.
  Do NOT activate for questions about public open-source documentation —
  use public sources for those.
---

# Internal Docs Navigator

When this skill is active, guide the user to the organisation's internal documentation
systems. You do not have direct access to these systems — your job is to direct
the user to the right place and help them craft effective searches.

## Documentation systems at the organisation

### Confluence — primary knowledge base
- URL: `https://confluence.company.com`
- Main spaces:
  - `PLAT` — Platform Team: infrastructure, developer tooling, internal libraries
  - `ENG` — Engineering-wide: architecture decisions, RFCs, onboarding guides
  - `OPS` — Operations: runbooks, incident playbooks, on-call procedures
  - `PROD` — Product: PRDs, roadmaps, feature specs
  - `SEC` — Security: policies, threat models, compliance guides

> **[PLACEHOLDER]** Replace the above spaces with your actual Confluence space keys
> and descriptions. Add or remove spaces as needed.

### GitLab — code and CI/CD docs
- Internal GitLab: `https://gitlab.company.com`
- CLAUDE.md files in each repo contain project-specific context
- Wiki tabs on individual projects for project-level runbooks

### Internal developer portal
> **[PLACEHOLDER]** If you have an internal developer portal (Backstage, Cortex, etc.),
> add its URL and describe what lives there vs Confluence.

## How to help the user find things

1. **Identify the domain**: Is this a platform/infra question (PLAT), a
   product question (PROD), an ops/incident question (OPS), or a security
   question (SEC)?
2. **Suggest the right space**: Direct them to the Confluence space most
   likely to contain the answer.
3. **Suggest search terms**: Propose 2-3 specific search terms they should
   try in Confluence.
4. **Suggest who to ask**: If you don't know where the docs live, suggest
   the right team or Slack channel.
   - Platform Team: `#platform-team` — developer tooling, CI/CD, internal libraries
   - DevOps / Infra: `#devops` — infrastructure, deployments, cloud resources
   - Security: `#security` — security policies, vulnerability reports
   - On-call: `#incident-response` — active incidents, escalation paths

> **[PLACEHOLDER]** Replace `#platform-team`, `#devops`, etc. with your actual
> Slack channels or communication tool equivalents.

## When docs don't exist

If the user is asking about something that probably isn't documented yet:
- Tell them it may not be documented
- Suggest they ask in the relevant Slack channel
- If they've just figured out the answer, encourage them to document it in
  the right Confluence space — mention that undocumented knowledge is a
  future incident waiting to happen

## What NOT to do

- Do not fabricate internal URLs, page titles, or Confluence content
- Do not guess at internal processes — always direct to the source
- Do not use public documentation as a substitute for internal docs when
  the question is clearly about an internal the organisation system or process

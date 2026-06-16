---
name: git-summary
description: >
  Summarise recent git activity for the current repository.
  Use when the user says "summarise recent commits", "what changed recently",
  "show me recent git history", or "git log summary".
  Do NOT activate for general code review or deployment tasks.
---

# Git Summary

Produce a short plain-English summary of recent repository activity.

## What to do

1. Run `git log --oneline -20` to get the last 20 commits.
2. Group commits by rough theme (feature, fix, chore, docs).
3. Write 3–5 sentences describing what changed and who was active.
4. Note any unusually large or risky commits (e.g. bulk deletes, dependency bumps).

## What NOT to do

- Do not modify any files.
- Do not push, commit, or stage anything.
- Do not access external URLs or APIs.
- Do not read files outside the repository working directory.

---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to `/tmp/`, not the repo.

Include a "suggested skills" section that names which skills the next agent should invoke (e.g. `/grill` will auto-fire anyway; flag `/diagnose`, `/tdd`, `/improve-codebase-architecture` if relevant).

Do not duplicate content already captured in other artifacts (the GitHub issue body, ADRs, commits, diffs). Reference them by URL or path instead. The bible (`docs/bible.md`) and overlays auto-load on next conversation, don't restate them.

Redact any sensitive information: API keys, passwords, session tokens, personal data about real people. When in doubt, redact.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

---
name: my-issues
description: Print the caller's own open GitHub issues ranked fastest-to-finish first, each with a plain-language explanation. Use when the user invokes /my-issues.
disable-model-invocation: true
---

# My issues

Answers "what should I pick up next" for whoever runs it: their own open issues, ordered by how little friction is left before they can start and finish.

## Quick start

```bash
python3 .claude/skills/my-issues/scripts/rank_issues.py
```

Prints `{"actionable": [...], "blocked": [...]}` to stdout. `--assignee @me` in the script means it's always "my issues" for whoever's `gh` session runs it.

## How the score works

The script counts mechanical signals only (no judgment):

- **unchecked checklist items** (`- [ ]` lines in the body) × 2, the concrete remaining work.
- **open questions** (bullet lines ending in `?`) × 3, unresolved before work can even start.
- **`PRD` label** → +10, a PRD is a container for a workstream, not a single finishable task; it will almost always sort last among actionable issues, and that's correct.
- **`ready-for-human` label** → +1 over `ready-for-agent`, `ready-for-agent` means fully specified already, marginally less friction to start.

Lower score = faster to finish. `needs-triage` / `needs-info` issues aren't scored, they're not actionable yet, so they go in a separate blocked bucket instead of being ranked by speed. `wontfix` issues are dropped entirely.

## Rendering the result (your job, not the script's)

For each issue in `actionable`, in score order, write:

1. `#<number>, <title>` with its rank.
2. **2-4 plain-language sentences** (English, no jargon, see `.claude/soul.md` rule 1) explaining what the issue is actually about and what "done" looks like. Read this from the issue's `body`, don't just repeat the title.
3. **Why this rank**: one line naming the actual signals that drove the score (e.g. "2 open checklist items, no open questions, ready-for-agent").
4. Labels (area, category, state role) and the issue URL.

Then list `blocked` separately, under a clear heading (e.g. "Not yet actionable"), each with its `blocked_reason` and, for `needs-info`, what's still being waited on if the body says so.

Keep the whole thing readable in one pass, this is a chat overview, not a file. Don't write anything to disk.

## Failure modes

- **`gh` not authenticated / not installed**: script exits 1 with the `gh` error on stderr, surface that directly, don't retry silently.
- **No open issues assigned**: empty `actionable` and `blocked`, say so plainly, don't invent placeholder issues.

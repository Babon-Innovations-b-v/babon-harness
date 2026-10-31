---
name: ralph
description: Autonomously work through the ready-for-agent queue, pick the top ready-for-agent issue, implement it from its agent brief under YOLO, verify the gates, ship, close, repeat. Use when the user wants to run ralph, clear the agent backlog AFK, or "run the agent loop".
---

# Ralph

The AFK execution loop on top of [`triage`](../triage/SKILL.md). Ralph clears the **`ready-for-agent`** queue: every such issue already carries a durable **agent brief** (its contract). Ralph implements them one by one under YOLO (`claude --dangerously-skip-permissions`), runs the gates that replace the permission prompts, ships, and continues.

Ralph only runs work that triage already declared agent-safe. It invents no scope and never touches a regulated path.

## What ralph picks up

`label:ready-for-agent`, oldest first (FIFO). Skip `LowPriority` cards until the rest is empty. Skip:

- anything on a **regulated path** (privacy/consent/security; that is `ready-for-human` per triage; if you find one mislabeled → set it to `ready-for-human` and move on),
- anything that is `blocked by` an open issue.

Empty queue → stop and report.

## Per issue

1. **Read the contract.** The agent brief is authoritative; body/discussion is context. If the brief is missing or too thin → back to `needs-triage`, comment why, next.
2. **Isolate.** Work in a fresh worktree (one issue = one worktree) so parallel/aborted runs do not pollute `main`. Put the issue on the board on `In Progress`: `python3 .claude/scripts/board-status.py <N> "In Progress"`.
3. **Build** the behavior from the brief. Reuse existing modules; `CONTEXT.md` vocab; `../../../docs/bible.md#workflowmodule-standard`. No scope beyond the Acceptance criteria.
4. **Gates** (these replace the permission prompts):
   - every **Acceptance** line of the issue,
   - the project's own test command (root `CLAUDE.md` names it, and what runs before a push),
   - the relevant `audit-*` skills on what you touched.
   Gate red → fix, or stuck after a real attempt → `ready-for-human` with notes. Never fake green.
5. **Ship.** Commit (scoped, imperative) + push to `main` (= deploy).
6. **Close.** [`close`](../close/SKILL.md) against the Acceptance list; close the issue, check off the parent PRD checklist. Next.

## Guardrails

- **`main` only**, push = deploy. One issue at a time.
- **Stop conditions:** queue empty, repeated gate failure on the same issue (propose stopping/investigating, do not loop endlessly and do not echo "awaiting direction"), or budget spent.
- **The gates** are the safety net that the skipped permission prompts would have been. A gate you did not run is a prompt you did not answer.
- **Finish it with your own access.** Ralph has whatever the main session has. An ops step you can run yourself (dry-run, run, verify) is yours to finish; do not hand it to `ready-for-human` merely because it touches something live. `ready-for-human` is for the real cases: human judgment or design, a decision with outside consequences, or an action that cannot be undone, not "it touches production".
- One line summary per issue (shipped / handed to human / skipped), so the run is auditable.

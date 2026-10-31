---
name: handoff_overseer
description: End a session by closing it and reporting to the overseer. Runs close, writes a handoff aimed at the overseer, and sends it to the overseer session. Use when the owner says "hand off to the overseer and close this one", or invokes /handoff_overseer.
disable-model-invocation: true
---

# Handoff to the overseer

A session started beside the overseer (the one coordinating session; there is no captain any more) finishes its shift cleanly, then reports to the **overseer** (`CONTEXT.md`) so it knows what changed without reading the transcript. Close first, so the report carries the final state.

## Steps

1. **Close.** Invoke [`close`](../close/SKILL.md) and follow it to the end. Done when close's one-line report is written: what shipped (commit hash on `main`), where each touched issue stands on the board, what is left.

2. **Write the handoff.** Follow [`handoff`](../handoff/SKILL.md), saved as `/tmp/handoff-<short-slug>.md`, with the overseer as the reader. Done when it has these four parts and repeats nothing the issue comment from step 1 already says (link it instead):
   - **Shipped and state:** commit, issue and board status, one line each.
   - **Left:** the open checklist, and who owns the next action.
   - **For the overseer:** anything that reaches past this session: shared files other sessions need to rebase over, a flaky test or a busy machine, a tool that did something surprising, a decision another workstream should hear about. Write "nothing" when there is nothing.
   - **Suggested skills** for whoever resumes.

3. **Find the overseer.** `ListAgents`; the overseer is the live session whose name says it coordinates (it contains "overseer"). Done when exactly one session is picked. None or several → `needs input:` asking the owner which one, and stop there.

4. **Send the report.** `SendMessage` to that name. The first line stands alone: which issue, that the session is closed, and the headline result. Then the "Left" and "For the overseer" parts as plain text, since the receiver sees text only and an `@` path attaches nothing, then the handoff file's path. Done when the send reports success; a delivery notice that it was held or refused goes into the final report.

5. **Report.** Tell the owner in two or three lines: what shipped, that the overseer was told (by name), what is left. End with the `result:` line.

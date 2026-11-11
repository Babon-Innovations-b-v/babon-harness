---
name: close
description: Cleanly end a work session. Finish the small stuff rather than writing it down, ship it, record where the PRD stands, move what only waits on time to the backlog, and stay open while anything still needs the user or is not done. Closes the PRD only when its work is actually finished, never just because the session is ending. Use at session end, or when the user says "close this out", "anything left?", "wrap up", or invokes /close.
---

# Close

A clean end to a session. A PRD can span many sessions, so the job is to leave it resumable, not to force it shut. Ship what is done, write down where it stands, and lose nothing to the chat.

**Close finishes work; it does not tidy it away.** The failure this skill exists to prevent is a session that ends with a neat list of small things it could have done in the time it took to write the list. If a loose end is in scope, do it now, here, before closing. Nothing is parked except what only time can finish, which goes to the backlog; what needs the user is asked, and the session stays open until it is answered.

## Steps

1. **Find the work.** The PRD/issue this session served: a `#N` from the chat, or infer it from the branch and commits. No issue and the work was real → run `to-prd` first. A throwaway question → nothing to close.

2. **Sweep.** `git status` + `git log` for what landed or is still uncommitted. Open threads in the chat: half-done edits, "I'll do X next", decisions not written down. A review finding still open goes on an issue, never in a code comment.

3. **Finish every loose end you can, then park the rest.** Take the list from step 2 one item at a time and ask a single question: can I do this now? If yes, do it, and let it ride out on this session's commit.

   **The bar is deliberately low.** A one-line fix, a stale sentence, a wrong comment, a missing test, a rename, a data update you have access for: all of that is smaller than the paragraph explaining why you left it. Three signs you are about to park something you should be doing: you are writing "worth doing if", "candidate", or "buys nothing today"; you are describing the fix precisely enough that doing it would be shorter; you are closing an issue while listing what is still wrong with it. In each case, stop writing and go do it.

   **A session does not close while something still needs the user or is not done.** Work that is not done gets done in this session, however big; "a session of its own" is not a reason to stop. Something that needs the user (a decision, an action only they can take, access you do not have) is asked now, in a few plain lines, and the session waits for the answer; it does not report closed with the question still open. The one thing that does not hold a session or a PRD open is **time**.

   **Waiting on time goes to the backlog.** A check that only passes once days go by (a week of green runs, a delete after seven clean days, an observation window) is not unfinished work: make it, or move it, to a sub-issue under the standing backlog PRD (`backlog_prd` in `.claude/project.json`) on the `LowPriority` board column, with the date it can be checked in its title or first line, and take it off the PRD's acceptance list. The PRD then closes when everything else is met. This is the one kind of new issue close may file without asking.

   "I did not want to widen the scope" is never a reason to leave something. Fixing what your own change left wrong is finishing, not scope creep.

   A parked line is written down, never filed as a new issue:
   - fits this PRD → its **Tasks** checklist;
   - a small task that fits no workstream → a checklist comment on the standing backlog PRD (its number is `backlog_prd` in `.claude/project.json`); if the project has areas, a small task in another area goes under that area's workstream PRD instead;
   - filing a **new issue** (sub-issue via `to-prd`, its own module PRD, a `ready-for-agent`/`ready-for-human` hand-off) needs the user's explicit go-ahead in this session; without it, park the checklist line and note "candidate issue" so the next session can ask. Several sessions each filing a few unasked issues reads as spam on the board.

   A decision you made goes where it survives compaction: an issue comment or `CONTEXT.md`. An ADR is offered, never written unasked (root CLAUDE.md). Finishing a loose end still means finishing it properly: run the tests, keep the tree clean, and if a one-liner opens into real work, that is the moment it becomes a parked line with a reason, not before.

4. **Ship.** The worktree must be clean when the session ends: run `git status --porcelain`, and either commit each path it names, stash it deliberately, or say in the step-5 comment why it stays. Work that exists only in a working tree is invisible to every gate, and the Stop hook (`.claude/hooks/leftover_guard.py`) blocks once on a dirty session worktree. Before committing, run the project's own test command, `python3 docs/adr/tools/check_index.py`, and any other pre-ship check root `CLAUDE.md` names. All must exit clean; a red gate is unfinished work, not a nit. Then commit scoped and push to `main` (root CLAUDE.md). Push is the ship: there is no PR step to catch what you skipped.

5. **Record where it stands.** Comment on the PRD: what shipped this session, what is left, the next step. Tick the **Tasks** lines that are done. This comment is the resume point for the next session.

6. **Set the board Status.** Every issue this session touched must match reality on the board, never skip this step. An issue that stays open with real work landed goes to `In Progress`: `python3 .claude/scripts/board-status.py <N> "In Progress"`. The standing backlog PRDs are the exception (the one in `backlog_prd` in `.claude/project.json`, and any other root `CLAUDE.md` names): they stay on `LowPriority` whatever landed under them. Closing an issue moves it to `Done` automatically, so skip that; but an issue that was already closed when it joined the board never gets the automatic move, set it by hand.

7. **Close only if done.** Re-check each **Acceptance** line from scratch. All genuinely met → close the issue, and the parent PRD too if it is fully done. Anything left → go back to step 3 and finish what you can, then leave it open with step 5's comment. An issue closed in the same breath as a list of what is still wrong with it was not ready to close. An issue whose work moves into another one (the owner's yes) is closed as **folded**, not done: `gh issue close N --reason "not planned"` with a comment `Folded into #M: <what moved>`, and its open tasks copied to #M first. When you close an issue, strip its triage-state labels (`needs-triage`, `ready-for-agent`, `ready-for-human`): those describe an open queue, and a closed issue that keeps them pollutes the board (`gh issue edit N --remove-label ...`).

8. **Hand off the assignee.** The board filters on the whole issue's assignee, so an open issue must be assigned to whoever owns the next action. For each issue that stays open (and each open parent of anything you closed): if the user's part is done and the rest belongs to someone else, remove the user and assign that person (`gh issue edit N --remove-assignee <user> --add-assignee <owner>`). Read the next owner from the open sub-issues or the issue body; if it is genuinely unclear, leave the assignee and say so in the step-5 comment.

9. **Report.** One line: what shipped, what moved to the backlog to wait on time, whether the PRD closed. If anything still needs the user or is not done, this is not the report: say what you need from them, or keep working. If the session ran in its own worktree and is finished with it, `ExitWorktree` with remove, or leave it for `.claude/scripts/worktree-reap.py` to name once it is clean and merged.

Team-facing text (comments, PRD edits) in English per [`.claude/soul.md`](../../soul.md). This skill closes a session; it does not open new scope.

---
name: update
description: Bring an already-set-up harness up to date with the latest improvements from the upstream project, Babon-Innovations-b-v/babon-harness. Use when the user says "update", "update the harness", "get the latest improvements", "update the server and everything on it", or during the monthly maintenance ask.
---

# Update

This repository came from the public project `Babon-Innovations-b-v/babon-harness`, which keeps improving. This skill takes those improvements into the owner's own copy without losing anything they changed.

Voice per `.claude/soul.md`: tell them what is new in plain words, one or two sentences per meaningful change, never a raw commit list.

## Flow

1. **Find upstream, then compare.** `git remote get-url upstream`; setup adds it when it makes the owner's private copy. Missing: `git remote add upstream https://github.com/Babon-Innovations-b-v/babon-harness.git` and say in one line that you reconnected it. If that address answers 404 (the project moved), ask `gh repo view "$(git remote get-url origin)" --json parent,templateRepository` for where the copy came from, and only then ask the owner once. Then `git fetch upstream` and `git log --oneline main..upstream/main` for what is new. Nothing new: say so in one line and stop.
2. **Tell them what they get.** Translate the new commits into owner language: "the meeting recorder got faster", "the deploy gate learned a new check". Ask nothing; updating is why they called.
3. **Merge, protecting their things.** `git merge upstream/main`. On a conflict, decide by who owns the file:
   - **Theirs wins**: `apps/website/` (their site), `design/` (their house style), `business/` (their documents and minutes), `.claude/memory/`, `.claude/soul.md` and `.claude/project.json` (their voice and their GitHub side), `CONTEXT.md` (their glossary), `apps/assistant/` persona and people files, and any file they created anywhere in the tree.
   - **Upstream wins**: the machinery, `infra/`, `apps/notulen/`, `apps/documents/`, `lib/`, `tools/`, `.claude/hooks/`, `.claude/scripts/`, `.claude/index/`, `.claude/skills/`, `.claude/settings.json`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, root `CLAUDE.md` and `README.md`, unless they deliberately customized the file (check `git log` for their own commits touching it; genuinely unsure, keep theirs and say so). `.claude/hooks/local/` is theirs when they added a hook there.
   - **Both sides matter**: `docs/bible.md` and `docs/adr/` hold the project's chapters and the decisions made in their own sessions. Merge, and never drop a section or ADR they added.
   - `config/` holds only the two `.example` files, which are upstream's; their real settings live in `config/harness.env`, which git ignores, and in the vault.
   Never lose a file they created.
4. **New settings check, before anything deploys.** Diff `config/harness.env.example` and `config/vault.env.example` between the old and new version. Any NEW key: decide its value (generate secrets with `openssl rand -hex 24`; ask the owner only if it is truly theirs to give), add a setting to `config/harness.env`, and add either kind to the vault with the update pattern in `.claude/skills/onboard/phases.md`. A new required compose variable that is missing would stop the stack at the next deploy; this step exists so that can never happen.
5. **Local update.** `uv sync --all-packages --all-extras --all-groups` so the laptop side matches, and `bash .claude/scripts/worktree-setup.sh` for the hooks path. If `.claude/` changed, mention that new abilities apply from their next conversation.
6. **Ship.** Push to `origin main`. The deploy gate tests the merge on the server; watch the commit's statuses (`gh api repos/<repo>/commits/<sha>/statuses`) until the deploy status is green, then confirm the root, `cloud.` and `notulen.` still answer.
7. **Report.** Two or three sentences: what arrived, that everything is healthy, and anything that needs them (a new optional feature they could turn on).

## Safety rules

- Never force-push, never rebase their main; merge only.
- If the merge goes badly wrong, `git merge --abort`, tell them plainly, and leave everything as it was; the server keeps running the last version that passed the gate regardless.
- If the gate holds the merge red, read why before anything else; fix forward in one commit rather than pushing the same merge again.

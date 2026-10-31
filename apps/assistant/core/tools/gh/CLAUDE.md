# apps/assistant/core/tools/gh/

GitHub reads through the `gh` CLI and the one write tool, `github_act`, on the repository named in `.claude/project.json`.

- **Nothing can be deleted.** Close with a reason, never remove.
- Assignees resolve through `people` in project.json; an unknown name is refused, because `gh` silently drops an unknown assignee.
- Writes need `ASSISTANT_GITHUB_WRITE` and `GITHUB_ASSISTANT_TOKEN`.
- A `gh` call that exits non-zero reaches the model as failed, never as an empty list.

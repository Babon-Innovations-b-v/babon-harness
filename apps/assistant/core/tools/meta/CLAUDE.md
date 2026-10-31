# apps/assistant/core/tools/meta/

Tools about the assistant itself and the repository: `bible`, `deploy_status` (the `vm/*` commit statuses the deploy loop posts), `repo_search`, `knowledge_search`, `stack_status`, `my_actions`, `whats_changed`, the memory writes and `readiness`.

- **A tool string naming its own failure is typed failed**, never ok.
- A memory write citing a commit or an issue no reading returned is refused.
- `whats_changed` derives its window from `ASSISTANT_BRIEF_TIME` and `ASSISTANT_ADVISOR_TIME`, the same settings the gateway's reports are declared from.

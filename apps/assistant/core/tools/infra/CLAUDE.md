# apps/assistant/core/tools/infra/

`db_query`, a SELECT-only read of the ops database (`OPENCLAW_DB_RO_URL`, read-only transaction), and `run_shell`, an allowlisted read-only shell.

- A wrong column is answered with the real columns of the tables the query names.
- `run_shell` scrubs secret env from the child and refuses redirects and pipes. Do not widen the allowlist with a binary that writes.

# lib/dashkit/CLAUDE.md

Shared FastAPI library behind every dashboard in this repository (notulen and anything you add). **Library, not application**: no entrypoint, no gates. Subpackages: `core` (app factory, SSO user, database connection, activity log, sync heartbeat, health checks), `ai` (the one metered Claude call), `frontend/` (static JS and CSS served at `/static/dashkit/*`).

## Boundaries

- **Worker images leave dashkit out on purpose.** `import dashkit` from GPU worker code fails; route a metric through a dashboard endpoint instead.
- **Self-contained.** dashkit imports nothing from `apps/` or `infra/`. Lean images copy only this directory.
- **No dashboard-specific tables here**, and never call Claude around `dashkit.ai.call_claude`: every call must land in `{domain}_ai_calls`.
- **Every `{domain}_*` table name goes through `core.identifiers.validate_table_name`** before it reaches an f-string.

## Identity

`core.auth.get_user(request.headers)` returns `Remote-User`, then `Remote-Email`, else `"anonymous"`. Caddy's `(oauth2_auth)` snippet sets both from oauth2-proxy and strips client-sent copies, so they are trustworthy only on routes that import that snippet. A route that must refuse strangers checks for `"anonymous"` itself.

## Database

`core.db.get_db()` connects with `DB_URL`, else `DB_URL_OPS`, else a DSN built from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST` (default `postgres`). It returns None when nothing is configured or the database is down; routes answer 503 or an empty payload. The driver is psycopg 3.

## Failure policy

Observability writes (activity log, AI-call accounting) are best-effort: fail open, log at WARNING, never break the feature. `fetch_activity` and heartbeat writes propagate. Inspector checks turn a per-check error into a `healthy: false` row, never a 500.

## AI calls

Never pass `temperature`, `top_p` or `top_k`: the `anthropic` SDK dropped them in 1.0.0 and passing one raises `TypeError` before the request, outside the error handling. Model and max_tokens defaults live in the optional `dashkit_ai_config` table.

## Frontend

No bundler: vanilla JS in an IIFE onto `window.dashkit`, shipped verbatim. `base.css` reads colours and fonts from `design/tokens.css` by variable name (`--color-*`, `--font-*`) with neutral fallbacks; change the look there, not here.

# apps/assistant/gates/

The FastAPI app and the MCP door: webhook routes, bearer auth, shape adapters. No decision logic here.

- Every route is bearer-gated with `OPENCLAW_WEBHOOK_SECRET` (and `_PREV` during a rotation).
- **One bad alert rejects the whole Alertmanager POST**, so Alertmanager retries the batch.
- The notify audit write is loud: a failure fails the POST so the caller's direct fallback fires.
- The door books each write to the person named in `requested_by`; only a short list of writes may be booked to the assistant itself.

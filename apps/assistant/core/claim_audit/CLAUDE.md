# apps/assistant/core/claim_audit/

The weekly said-versus-seen check: what the assistant told people, set against what its tools had read when it said it.

- The report goes to Talk from the server side (`watch/claim_audit/`), never to Signal: it is about sending too many unchecked messages, and a page about that would be one more.
- A week the audit could not read is reported as unread, never as clean.

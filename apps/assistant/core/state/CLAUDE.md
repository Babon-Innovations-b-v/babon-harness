# apps/assistant/core/state/

SQLite table adapters, one file per table. `conn.py` is the connection seam; the database is `OPENCLAW_STATE_PATH` on the `assistant_state` volume.

- **Writes are loud.** A failed write fails the webhook so the sender retries.
- Single writer: the door runs one worker. Scaling it means moving state first.
- A mute that would cover something that paged critical is refused unless forced.
- The worklist line says when a person was last told in a send; only that counts as told, never a note.

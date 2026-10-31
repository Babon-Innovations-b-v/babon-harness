# apps/assistant/core/

The decisions: triage, the notify pen and its flush, patrol, the weekly compact, page holding and rendering, and the guards every outgoing sentence crosses (`claims.py`, `signal_text.py`, `voice.py`).

## Do not get wrong

- **One voice, no banners.** A human-facing loop sends with an empty subject; a subject adds a banner meant for machine pages.
- **A sentence a tool did not back does not leave.** The claim guards nudge once, then drop the sentence. Do not loosen a guard to make a test pass; fix the reading.
- **Recipient is `SIGNAL_RECIPIENT`, else the first `SIGNAL_ALLOWLIST` entry.** Never the bot's own number.
- **The pen honours suppressions**, and the flush clock is read before a silenced ping is cleared, or every silenced ping holds the real page a full gap.
- **A new send road passes `loop=` to `remember_sent`** and is listed in `RELAYED_LOOPS`, or the chat never sees what was sent.
- Clock times a person reads are written on `ASSISTANT_TIMEZONE` through `shared/local_time.py`; never format a local time by hand.

# apps/assistant/shared/

Plumbing every layer uses: auth, the Anthropic client and pricing, the daily budget, Signal sending (`signal.py` over `notify.py`), local time, and the three settings modules (`name.py`, `zone.py`, `project.py`).

- No view code here.
- `notify.py` is standard library only and never raises; it returns which channels took a message.
- Read the name, the zone and the repository from the settings modules, never from a literal.

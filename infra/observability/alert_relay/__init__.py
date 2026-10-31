"""Alertmanager webhook receiver: hands alerts to the assistant, or sends them
raw to Signal while the assistant deadman flag is fresh. `app.py` is the
transport, `relay.py` the decision. Nothing is re-exported."""

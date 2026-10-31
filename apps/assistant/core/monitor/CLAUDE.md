# apps/assistant/core/monitor/

The stack sweep: a background thread in the door that checks every component in `registry.py` and fills the notify pen when one goes down.

- **The monitor does not send. It fills the pen.** Batching and muting belong to `core/notify_flush.py`.
- **An entry earns its place only where nothing else sees the failure.** Never add a check a Prometheus rule already pages on.
- **`unknown` never counts toward down.** A check whose credentials are missing classifies unknown, so an unwired check cannot page.
- A heartbeat component's window is sized against the emitter's cadence, never the watched thing's, or one dropped post flips it down.
- `MONITOR_HTTP_TARGETS` and `MONITOR_DEPLOYMENTS` add entries without code.

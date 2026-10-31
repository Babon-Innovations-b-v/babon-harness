# apps/assistant/core/monitor/checks/

One file per check kind: http, heartbeat, db, kubectl, external. Each returns up, down or unknown and never raises.

- A missing credential or an unreachable third party is `unknown`, never `down`.
- A deployment scaled to zero on purpose is parked, not down.

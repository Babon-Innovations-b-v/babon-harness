# infra/observability/CLAUDE.md

How the server finds out something broke and tells the owner's phone. Chapter: `infra/observability` in `docs/bible.md`.

## Shape

```
Prometheus -> Alertmanager -> alert-relay -> assistant /webhook/alertmanager -> Signal
                                   |  (assistant-down flag fresh)
                                   +-> signal-cli /v2/send -> SIGNAL_RECIPIENT
```

`compose.yml` runs prometheus, alertmanager, node-exporter, blackbox-exporter, alert-relay and the one-shot probe-targets. Host-side jobs are systemd units in `systemd/`, installed by `systemd/install.sh`, run with the system `python3` from `$HARNESS_ROOT/repo`.

## Do not get wrong

- **Standard library only** in `alerts/`, `alert_relay/`, `node_textfile/`, `probes/`. The units use the system python3 and the relay runs on a bare `python:3.12-slim` with this directory mounted, so a third-party import is a dead pager.
- **A deadman never pages through the assistant.** `assistant_deadman`, `gateway_deadman`, `dead_mans_switch` and the canary's recovery message call `fan_out(..., signal_direct=True)`. Removing that makes the canary for "assistant down" depend on the assistant.
- **The relay's flag read fails toward "up".** A flag older than 300 s is stale, because the deadman rewrites it every 60 s. Change both numbers together or never.
- **The relay never swallows.** A refused forward or a failed send answers 500 so Alertmanager retries.
- **`/var/lib/harness` must be mounted into alert-relay.** Without it the raw road can never engage; the relay logs that and `/assistant-check` reports `flag_mount_present: false`.
- **Only `Watchdog` goes to `null-receiver`.** Every other alert must reach the relay; `dead_mans_switch.py` reads `Watchdog` from the API and pages when it is unseen for an hour.
- **Metric names are a contract.** The deploy loop writes `harness_deploy_last_success_timestamp_seconds` to `/var/lib/harness/textfile/*.prom`; `rules/harness.yml` reads it. Rename both in one commit.
- **The Signal send canary's failure is not paged over Signal** (`SIGNAL_UNDER_TEST_UNITS`). It tells you once sending works again.
- A new harness timer job gets `OnFailure=harness-notify-failure@%n.service` and the `harness-` prefix, or its failure is silent and invisible to `UnitFailed`.

## In the cluster (`infra/k8s/monitoring`)

- Image `ops-runner` (`Dockerfile.ops-runner`, compose service `ops-runner`, profile `cluster-image`) holds only this directory; the deploy loop builds it.
- A job keeping state on `alert-state` is a container in the alert-relay pod, never a CronJob: one writer per claim.
- Compose must not load `rules/cluster.yml`. `textfile.publish` pushes to `PUSHGATEWAY_URL` when set.

## Ports (loopback only)

| Port | What | Used by |
|---|---|---|
| 9090 | Prometheus | you, through an SSH tunnel |
| 9094 | Alertmanager | `harness-dead-mans-switch` |
| 9095 | alert-relay | `harness-assistant-deadman` |

The host jobs also expect, from the assistant's compose: signal-cli on `127.0.0.1:8080`, the assistant on `127.0.0.1:$OPENCLAW_PORT`, the gateway health route on `127.0.0.1:18789/healthz` (override with `ASSISTANT_GATEWAY_HEALTH_URL`).

## Commands

- Tests: `python -m pytest infra/observability/tests`
- Rule tests: `docker run --rm -v "$PWD/infra/observability/prometheus:/p:ro" -w /p/tests --entrypoint promtool prom/prometheus:v3.4.1 test rules harness.test.yml`
- Config check: `promtool check config`, `amtool check-config`, same images.
- What a unit paged: `journalctl -u harness-notify-failure@<unit>.service`

## Optional

`LOKI_URL` is not used here. To ship logs, run a log shipper of your choice next to this stack and point it there; nothing in the alert path depends on it.

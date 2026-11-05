# apps/assistant/watch/

Passes that watch the assistant from outside its container, run by the systemd timers in `apps/assistant/systemd/` on a compose host and by the CronJobs in `infra/k8s/assistant/schedule.yaml` in the cluster as `python -m apps.assistant.watch <pass>`. The gateway is watched from `infra/observability/alerts/gateway_deadman.py`, not from here.

- **The exit code is the decision to page, and the passes disagree on purpose.** Read `run.py`'s header before changing one.
- A subcommand not in `run.PASSES` is a dead timer.
- A read timeout on a trigger is not retried: the door took the request.
- The chat relay runs the gateway CLI as `docker exec <ASSISTANT_GATEWAY_CONTAINER>`, or behind `ASSISTANT_GATEWAY_EXEC` when set (the cluster's `kubectl exec`).

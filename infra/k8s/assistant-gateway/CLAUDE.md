# infra/k8s/assistant-gateway/

The upstream OpenClaw gateway alone (Service `gateway:18789`, claim `gateway-data`, subPaths `gateway_state` and `assistant_workspace`).

- **Deploy nothing else into this namespace.** Whatever execs into the gateway (the workspace apply, the chat relay) gets a grant that reaches every pod here.
- **Its DNS search path adds namespace `assistant`**, so `assistant:8000` and `signal-cli:8080` in its config resolve unchanged. Keep `dnsConfig` if you touch the pod spec.
- `apps/assistant/workspace/apply.sh` and the chat relay still call `docker compose exec`; in the cluster they need `kubectl -n assistant-gateway exec deploy/gateway --`, which they do not do yet.

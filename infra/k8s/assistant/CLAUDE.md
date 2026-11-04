# infra/k8s/assistant/

The door (Service `assistant:8000`), signal-cli (`signal-cli:8080`) and the speech model (`whisper:8000`, zero replicas until `ASSISTANT_VOICE=1`). The gateway is in `../assistant-gateway`. App rules: `apps/assistant/CLAUDE.md`.

- **signal-cli is one replica, `Recreate`, always.** Two clients on one number lose messages. The gateway is the only receiver; there is no separate receive loop.
- **NetworkPolicy `signal-cli-callers` is signal-cli's only gate**: the door, the gateway pod and the alert relay's pod in `monitoring` (its deadmen page while the door is down), nothing else. Anything new that must page goes through the door.
- **The door has no kubeconfig here**, so its kubectl tools are off.
- Copy `signal_data` before the compose signal-cli stops for good, with both stopped (migration recipe in `../CLAUDE.md`); a lost account means re-linking.
- The scheduled triggers (`apps/assistant/systemd/`) still run on the compose host; they are not ported here.

# infra/webhook/

The push receiver. GitHub POSTs every push to `https://deploy.$DOMAIN/hooks/deploy`;
Caddy proxies `/hooks/*` to the adnanh/webhook listener on the host
(`systemd/harness-webhook.service`, port 9000), which checks the HMAC-SHA256
signature against `DEPLOY_WEBHOOK_SECRET` and runs `trigger-deploy.sh` for a push
to `refs/heads/main`. The two-minute deploy timer is the backstop.

## Rules

- **The secret never lands in a file of its own.** `hooks.json.template` is
  rendered by webhook itself (`-template`) from the environment the unit loads
  from the vault cache. A new vault version restarts the listener (step 80).
- **The repair lives in `trigger-deploy.sh` and nowhere else.** It parks dirty
  tracked files in `$HARNESS_ROOT/repo-selfheal/<time>/` before resetting the
  clone; nothing is ever destroyed. The deploy cycle only fast-forwards.
- **Alert only for what could not be fixed**, or when someone's edits were
  parked. A reset that lost git's index lock is a race with the cycle's own
  fast-forward, and pages nobody.
- **Keep the log line `commit <sha8> `**: step 15 greps for it to tell a push
  the listener saw from one only the timer brought in.
- Port 9000 must stay closed in the firewall; only Caddy should reach it.

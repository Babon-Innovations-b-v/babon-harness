---
name: troubleshoot
description: Investigate and fix a misbehaving harness. Gathers the facts from the server (running services, logs, auto-deploy state, disk, certificates), explains the finding in plain words, and fixes it after a yes. Use when anything sounds broken: the website is down, minutes never arrived, a login fails, an error appeared, "something is broken", or the user describes any behavior that does not match what they expected.
---

# Troubleshoot

The user may not be able to describe the problem technically. Ask them exactly one question: "What were you trying to do, and what did you see instead?" Then investigate yourself; never ask them to run anything.

## Gather the facts

Server address and domain are in `config/harness.env` (SERVER_IP, DOMAIN, HARNESS_ROOT, default `/opt/harness`); run remote commands over ssh as the `harness` user. `compose` below is `docker compose --env-file $HARNESS_ROOT/harness.env` in `$HARNESS_ROOT/repo`. Announce each step in one plain sentence before running it.

1. Is the server reachable at all? (`ping`, `ssh`). If not, check the instance state with `scw instance server list` before anything else.
2. What did the last push do? The commit page on GitHub carries the server's own statuses (gate, build, boot, swap, deploy): `gh api repos/<repo>/commits/<sha>/statuses`, with `<repo>` from `.claude/project.json`. A red gate means the deploy held the old version on purpose; read its description before anything else.
3. On the server: `compose ps` to see which services are up, restarting, or gone.
4. For every service that is not healthy: `compose logs --tail 50 <service>`.
5. Auto-deploy: its systemd units and log paths are named in `infra/auto-deploy/CLAUDE.md`; read the last cycle's journal and compare the checked-out commit with `origin/main`.
6. Disk space (`df -h /`) and memory (`free -h`). A full disk is the most common silent killer.
7. HTTPS and sign-on: does `https://<DOMAIN>` respond, does a gated name redirect to `auth.<DOMAIN>`, and what do Caddy and oauth2-proxy say (`compose logs --tail 50 caddy oauth2-proxy`)?
8. What the monitoring already knows: Prometheus alerts (`compose exec -T prometheus wget -qO- localhost:9090/api/v1/alerts`) usually name the broken thing before you find it.
9. Anything the user's description points at specifically. Minutes missing: the bucket, the Anthropic key, GITHUB_NOTULEN_PAT. The assistant silent: its gateway logs, signal-cli's registration, and quiet hours (it holds pages at night on purpose).

## Report, then fix

- Explain what you found in plain words, two or three sentences, no jargon without a one-line explanation. If several things are wrong, name the root cause first.
- Propose the fix and what it will do, in one or two sentences, including whether anything will restart or be briefly offline.
- Apply the fix only after they say yes. Verify afterwards with the same check that first showed the problem, and show them it now passes.
- If you cannot find the cause, say so honestly, state what you ruled out, and suggest the next diagnostic step rather than guessing at fixes.

## Hard rules

- Never delete data as a fix without explicit, separate confirmation.
- Never print secrets from the vault or harness.env into the chat.
- End with a plain-words summary: what was broken, why, what changed, and how they can tell it is healthy now.

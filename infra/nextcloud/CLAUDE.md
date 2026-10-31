# infra/nextcloud/

Postgres, Nextcloud, its cron container and oauth2-proxy (`compose.yml`), plus the scripts that keep Nextcloud the stack's one login. Accounts are made in Nextcloud; there is no other account service.

## Rules

- **Nextcloud is the identity provider.** Its `oidc` app issues the client oauth2-proxy uses; `oidc-setup.sh` creates it (client name `harness-sso`) and registers `https://<sub>.$DOMAIN/oauth2/callback` for every entry in `SSO_SUBDOMAINS`. Re-run it after adding a subdomain.
- **oauth2-proxy runs `--cookie-expire=8h --cookie-refresh=0s`.** The oidc app gives no refresh token, so a refresh ends the session; a long cookie lets a disabled account in for as long as it lives. `session-lifetime-assert.sh` reports drift on those flags and restores the three 7-day Nextcloud values. Keep the flags in `command:` so `docker inspect` can see them, and secrets in `environment:`.
- **`nextcloud-2fa-enforce.sh` is fail-closed** and does nothing until `NEXTCLOUD_2FA_ENFORCE=1`. Never bypass the "every user enrolled" check: it is what stops a lockout.
- **Every `occ` call ends in `</dev/null`.** `docker compose exec -T` reads stdin and would swallow the user list a loop is reading.
- **Scripts read the env file with `env_get`, never `source` it**: values may contain spaces.
- **`postgres-init.sh` runs only on an empty data volume.** Changing it does nothing to a running database.
- **Postgres binds 127.0.0.1 by default.** Docker's published-port rule runs ahead of ufw, so a wider `POSTGRES_BIND_ADDRESS` is not closed by a host firewall.
- Background jobs run in the `nextcloud-cron` container; there is no host timer.
- Nextcloud and oauth2-proxy are pinned upstream images, unmodified. Move Nextcloud one major version at a time.

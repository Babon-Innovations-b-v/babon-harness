# Onboard phases

Each phase: **Already done?** check first, then the work, then the **Verify** check. Announce each phase in one plain sentence before starting it.

Paths below use the defaults: `HARNESS_ROOT=/opt/harness`, the repository checked out at `/opt/harness/repo`, the pulled env cache at `/opt/harness/harness.env`, the vault secret `harness-env`. When `config/harness.env` overrides one, use its value. `compose` below is short for `docker compose --env-file /opt/harness/harness.env` run in `/opt/harness/repo`.

## The vault, and how to update it

Secrets never live in files the user keeps. They live in the vault: one Scaleway Secret Manager secret (`VAULT_SECRET_NAME`) whose content is the stack's full KEY=value environment; every change is a new version. `config/harness.env` on the laptop holds only non-secret settings, and they are repeated inside the vault so compose on the server sees them.

Every phase that changes an environment value uses this one pattern:

1. Fetch the current content to a temp file, mode 600, never echoed: `scw secret secret list name=harness-env -o json` for the `id`, then `scw secret version access <secret-id> revision=latest raw=true > "$TEMP_ENV" && chmod 600 "$TEMP_ENV"`.
2. Edit the KEY=value lines in the temp file.
3. Push it back as a new version: `infra/secrets/push-env.sh "$TEMP_ENV"`, then `rm -f "$TEMP_ENV"`.
4. Apply on the VM: `ssh harness@<SERVER_IP> /opt/harness/repo/infra/secrets/pull-env.sh` and restart the affected service, or wait one auto-deploy cycle (it pulls the vault every run and redeploys when the env changed).

Batch related edits into one version; never print the content.

**One writer at a time.** Steps 1 to 3 are a read-modify-write and nothing locks the secret. Two actors that both fetched before either pushed each push their own snapshot, so the second silently drops the first's values. The orchestration section of [SKILL.md](SKILL.md) says which actor holds the pen.

## Phase 0: explain the plan

Tell the user, in a few lines, roughly this:

> I am going to set up your harness: a server at Scaleway running your website, your private file cloud (which is also the one login for everything), Notulen (the meeting recorder), and an assistant you message on Signal that knows your calendar, your repository and the health of the server. A GPU transcription engine runs only when a recording comes in and costs cents. It takes about an hour of my work and about twenty minutes of yours, in short bursts: a GitHub login, a Scaleway account with a payment method and an API key, your domain, names for your cloud accounts, QR codes to scan, and a few optional keys. The server costs roughly 15 to 25 euros per month.

Then start phase 1 without waiting, unless they object.

## Phase 1: laptop tools and GitHub

**Already done?** `gh auth status` succeeds, `gh repo view "$(git remote get-url origin)" --json isPrivate,owner --jq '.owner.login + " " + (.isPrivate|tostring)'` reports their own login AND `true`, and `.claude/project.json` names that repo. Then skip.

1. Verify the prerequisites print a version: `git --version`, `curl --version`, `python3 --version`, `uv --version`, `claude --version`. `uv` missing: install it with the astral.sh script, no sudo. `git`, `curl` or `python3` missing: stop and give the one copy-paste line from SKILL.md.
2. Install the GitHub CLI if missing, WITHOUT sudo: resolve the latest tag from `https://api.github.com/repos/cli/cli/releases/latest`, download the release archive for this OS and `uname -m`, extract the `gh` binary to `~/.local/bin/gh`, `chmod +x`, make sure `~/.local/bin` is on PATH. Verify `gh --version`.
3. Log in (**question 1**): ask whether they have a GitHub account; if not, send them to github.com/signup and wait. Then `gh auth login --hostname github.com --git-protocol https --web` and `gh auth setup-git`.
4. If `git config user.name` or `user.email` is empty, set them from `gh api user` (the noreply email if none is public).
5. Give them their own private copy. Test **visibility**, not ownership, and always pass the origin URL explicitly (a bare `gh repo view` prefers the `upstream` remote this step creates). Make the private copy unless origin is both theirs and private:
   - Read where origin came from first: `gh repo view "$(git remote get-url origin)" --json parent --jq '.parent | if . then .owner.login + "/" + .name else empty end'`. Empty means a plain clone, so rename origin to `upstream`; non-empty means a fork, so point `upstream` at that parent.
   - `gh repo create harness --private` under their account (add a short suffix if the name is taken, tell them which), add it as `origin`, `git push -u origin main`.
   - Why it must be private: their minutes, their memory notes and their assistant's people list land in this repository.
6. Run `python3 .claude/scripts/setup-github.py`, which writes the repo, owner, board and people into `.claude/project.json`. Commit and push the result.
7. Run `bash .claude/scripts/bootstrap.sh` from the repo root (hooks path, memory link, the repository index). One sentence: this makes my notes about your setup live inside the project.

**Verify**: `gh auth status` ok; origin theirs and private; `.claude/project.json` has `repo` filled; `git push` works.

## Phase 2: Scaleway CLI

**Already done?** `scw account project list` returns a project table. Then skip.

1. Install scw if missing, WITHOUT sudo: resolve the latest release from `https://api.github.com/repos/scaleway/scaleway-cli/releases/latest`, save the matching binary as `~/.local/bin/scw`, `chmod +x`, verify `scw version`.
2. **Question 3**, the API key: "Go to https://console.scaleway.com, log in, IAM, API keys, Generate API key. Copy the Access key and the Secret key and paste them here; the secret is shown only once." No account yet: https://www.scaleway.com, "Continue with GitHub", then a payment card under Billing (prepaid and most virtual cards are refused; a normal bank card or a SEPA mandate works).
3. Configure non-interactively, never through `scw init`: `scw config set access-key=<ACCESS> secret-key=<SECRET>`, then `scw account project list` for the ids, then `scw config set default-project-id=<id> default-organization-id=<id> default-region=fr-par default-zone=fr-par-1`. Region is your decision: `fr-par` unless another Scaleway region is clearly closer to them.

**Verify**: `scw account project list` shows at least one project.

## Phase 3: settings file + the vault

**Already done?** `config/harness.env` exists with a real DOMAIN, and `scw secret secret list name=harness-env -o json` finds the secret with at least one enabled version. Then skip.

1. Write `config/harness.env` from `config/harness.env.example` if it does not exist. It is git-ignored; it holds settings only.
2. **Question 2**: "Which domain should the harness live on? It needs one you control, because the single sign-on and the certificates are per subdomain. If you have none, I can register one at Scaleway, about 10 euro a year on the same bill."
   - **Owns one elsewhere**: DOMAIN is that name; DNS happens in phase 5 at their registrar.
   - **Wants one**: check it with `scw domain domain search domains.0=<name>`, say the real yearly price, and on their yes register it with `scw domain order buy` (one short ask for the registrant contact). Its DNS is then yours to manage by command.
3. Fill the settings you can already decide: DOMAIN, ACME_EMAIL (their GitHub email unless they say otherwise), SCW_REGION, HARNESS_ROOT, VAULT_SECRET_NAME, ASSISTANT_TIMEZONE (from the laptop's `timedatectl` or `date +%Z`), AGENDA_BASE_URL (`https://cloud.<DOMAIN>/remote.php/dav`), S3_ENDPOINT and S3_REGION for the region. Leave SERVER_IP for phase 4. The rest keep their example defaults.
4. Assemble the FULL environment in a temp file (mode 600), never in config/harness.env:
   - Start from `config/vault.env.example`, plus every line of config/harness.env. If the vault already has a version (resuming), start from that instead and only fill what is still empty; never regenerate a value that exists.
   - Generate locally, never printed: one `openssl rand -hex 24` each for POSTGRES_PASSWORD, NEXTCLOUD_DB_PASSWORD, NEXTCLOUD_ADMIN_PASSWORD, DEPLOY_WEBHOOK_SECRET and OPENCLAW_WEBHOOK_SECRET; one `openssl rand -hex 32` for OPENCLAW_GATEWAY_TOKEN; and OAUTH2_PROXY_COOKIE_SECRET as exactly 32 random bytes, url-safe: `python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`. Hex, not base64, for anything that ends up inside a database URL. Set NEXTCLOUD_ADMIN_USER to `admin`, POSTGRES_USER and POSTGRES_DB to `harness`, NEXTCLOUD_DB_NAME and NEXTCLOUD_DB_USER to `nextcloud`.
   - Write the literal value `pending` for anything a later phase fills: S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, ANTHROPIC_API_KEY, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET. Compose refuses an empty required value; `pending` lets the stack come up and the phase that owns the value replaces it.
5. Push it: `infra/secrets/push-env.sh <temp file>`, then delete the temp file. One sentence: "Your passwords now live in Scaleway's secret vault; config/harness.env on this laptop keeps only harmless settings."
6. Company profile, only if it applies: if `git ls-files --others --exclude-standard business/ design/` lists files they added, offer to extract their company name, address, registration and VAT numbers, IBAN and logo into `design/company.yaml` for the documents app. Only values literally present in their files; never invent.

**Verify**: config/harness.env holds settings and nothing secret; the vault has at least one version.

## Phase 4: create the server

**Already done?** An instance named `harness` exists and SERVER_IP in config/harness.env matches its public IP. Then skip.

1. If `~/.ssh/id_ed25519` does not exist, `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`. If `scw iam ssh-key list` lacks its public half, `scw iam ssh-key create name=harness-laptop public-key="$(cat ~/.ssh/id_ed25519.pub)"`.
2. `scw instance server list name=harness`: reuse one if it exists.
3. Otherwise say in one line that the paid part starts now, then `scw instance server create type=DEV1-L zone=<zone> image=ubuntu_noble root-volume=local:80GB name=harness ip=new`. The root volume size is not optional: the default is the image minimum and the stack does not fit. If the type is unavailable, pick the closest current type with at least 8 GB of memory and say which.
4. Wait until it is running with a public IP, then retry `ssh -o StrictHostKeyChecking=accept-new root@<IP> true` for a couple of minutes.
5. Write `SERVER_IP=<IP>` into config/harness.env and into the vault (update pattern).

**Verify**: `ssh root@<IP> true` succeeds; SERVER_IP saved in both places.

## Phase 4a: the cluster

**Already done?** CLUSTER_ID is set in config/harness.env, `infra/cluster/create-cluster.sh` plans no `would:` line, and `kubectl -n assistant get externalsecret harness-env` says `SecretSynced`. Then skip.

`infra/cluster/CLAUDE.md` holds the rules; read it first. The cluster's control plane is free; a pool bills from the moment it has a node. Node prices and boot times are the provider's list, not measured here: say that, do not quote a number.

1. Copy the `# --- Cluster` block of `config/harness.env.example` into config/harness.env if it is missing. The defaults are a working start; change a pool role only when the owner asks.
2. Plan: `bash infra/cluster/create-cluster.sh`. It only reads, and prints every change. Read it; a refused machine type shows up here as a missing type, so swap it for the closest current one in `POOL_<ROLE>_TYPES` and plan again.
3. Install `helm` into `~/.local/bin` if missing (release tarball, no sudo).
4. Say in one line that the paid part of the cluster starts now, then `bash infra/cluster/create-cluster.sh --apply`. It creates or adopts the cluster named `CLUSTER_NAME`, its pools and their stock fallbacks, and writes CLUSTER_ID and SCW_PROJECT_ID back into config/harness.env.
5. The secret store's key: an IAM application `<CLUSTER_NAME>-vault-reader` with one policy, permission sets `SecretManagerReadOnly` and `SecretManagerSecretAccess` on SCW_PROJECT_ID only, and an API key for it. Never print the secret key. Its two halves go in the vault as ESO_ACCESS_KEY and ESO_SECRET_KEY, with CLUSTER_ID and SCW_PROJECT_ID, in one version (update pattern).
6. With a private copy of the vault: `bash infra/cluster/create-cluster.sh --apply --vault-env <copy>`. It copies the key into the cluster and applies `infra/k8s/`. Delete the copy.

In the parallel block this is worker A's: it runs steps 1 to 4, creates step 5's key and returns its halves without writing the vault; step 5's vault version and step 6 run in the closing block.

**Verify**: CLUSTER_ID saved in both places; `kubectl get nodes -L <POOL_ROLE_LABEL>` shows the system pool's node; the ExternalSecret `harness-env` in `assistant` is synced.

## Phase 5: DNS

**Already done?** Every name the Caddyfile serves resolves to SERVER_IP. List them with `grep -oE '^[a-z0-9.-]*\{\$DOMAIN\}' infra/caddy/Caddyfile` (the bare `{$DOMAIN}` is the root), and check each with `python3 -c "import socket; print(socket.gethostbyname('<name>'))"`.

- **Scaleway-registered domain**: create the A records yourself with `scw dns record` on the zone, one for the root and one per subdomain, all pointing at SERVER_IP.
- **Domain owned elsewhere**: print a table of `A` records (`@` plus every subdomain from the list above, each with SERVER_IP), explain in one sentence where they add them (the registrar's "DNS" or "Zone" page), and poll the resolution checks every 30 seconds. DNS spread can take minutes to hours; do not start phase 6 until every name resolves.

**Verify**: every name resolves to SERVER_IP.

## Phase 6: deploy the stack

**Already done?** The root and `cloud.` answer 2xx/3xx over HTTPS, the gated names (`notulen.`, `deploy.`) answer 2xx/3xx or a redirect to `auth.`, and `systemctl list-timers` on the VM shows the auto-deploy timer. Then skip.

Work over ssh as root for steps 1 to 4, then as `harness` for ever after.

1. `apt-get update && apt-get upgrade -y`.
2. Create the `harness` user if missing, copy root's `authorized_keys` to it (mode 600), and give it passwordless sudo in `/etc/sudoers.d/harness`, mode 440.
3. Install Docker Engine and the compose plugin (`curl -fsSL https://get.docker.com | sh`), add `harness` to the `docker` group, verify `docker compose version`.
4. Add a 4 GB swap file if `swapon --show` is empty, with its `/etc/fstab` line.
5. Deploy key: as `harness`, `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C harness-vm-deploy` and `ssh-keyscan github.com >> ~/.ssh/known_hosts`; register the public half read-only with `gh repo deploy-key add <file> --repo <owner>/<name> --title "harness vm (read-only)"` unless that title exists.
6. `sudo mkdir -p /opt/harness && sudo chown harness:harness /opt/harness`, then `git clone git@github.com:<owner>/<name>.git /opt/harness/repo` (or `git -C /opt/harness/repo pull --ff-only`).
7. The VM's own scoped way into the vault. **Skip if `/opt/harness/scw-secrets.env` exists on the VM.**
   - From the laptop: `scw iam application create name=harness-vm -o json` (reuse an existing one).
   - One policy, this project only: `scw iam policy create name=harness-vm-secrets application-id=<app-id> rules.0.permission-set-names.0=SecretManagerReadOnly rules.0.permission-set-names.1=SecretManagerSecretAccess rules.0.permission-set-names.2=BillingReadOnly rules.0.project-ids.0=<project-id>`. ReadOnly alone can list secrets but not read their values; both are needed.
   - An API key for it with an expiry a year out: `scw iam api-key create application-id=<app-id> expires-at=<ISO date> -o json`. Note the renewal date for phase 12.
   - Write `/opt/harness/scw-secrets.env` on the VM, owned by `harness`, mode 600: `SCW_ACCESS_KEY`, `SCW_SECRET_KEY`, `SCW_DEFAULT_PROJECT_ID`, `SCW_DEFAULT_REGION`, and the vault secret's id. Read `infra/secrets/pull-env.sh` for the exact variable names it expects. The laptop's own key never lands on the VM.
   - As `harness`, run `/opt/harness/repo/infra/secrets/pull-env.sh` and check `/opt/harness/harness.env` exists, mode 600.
8. Start everything: `compose up -d --build`. Caddy fetches certificates, which takes a minute or two. oauth2-proxy stays unhealthy until phase 7 replaces the `pending` OIDC values; that is expected and nothing else depends on it.
9. Install auto-deploy: follow `infra/auto-deploy/CLAUDE.md` (it names the installer for the systemd units and the webhook). From then on every push to `main` goes through the deploy gate and is live within a few minutes. Also install kubectl for the `harness` user into `~/.local/bin`, no sudo, for the GPU tier's checks.
10. Verify with retries while certificates settle (up to about five minutes): `curl -fsSL -o /dev/null -w '%{http_code}' https://<DOMAIN>` and `https://cloud.<DOMAIN>`; `compose ps` shows the services up.

**Verify**: the root and `cloud.` respond over HTTPS; `compose ps` healthy apart from oauth2-proxy; auto-deploy timer active. From here on, ssh as `harness`, never root.

## Phase 7: Nextcloud accounts, 2FA and the single sign-on

**Already done?** The everyday accounts exist (`occ user:list`), `infra/nextcloud/nextcloud-2fa-enforce.sh --check` reports everyone enrolled AND `enforcement: ON`, the vault's OIDC_CLIENT_ID is not `pending`, and `https://notulen.<DOMAIN>` redirects an anonymous browser to `auth.<DOMAIN>`. Then skip.

`occ` is Nextcloud's admin tool: `compose exec -T -u www-data nextcloud php occ ...`.

1. Wait until `https://cloud.<DOMAIN>` serves the login page (first boot installs itself).
2. **Question 5**: the account names, one short lowercase username per person.
3. Create each with a generated temporary password: `compose exec -T -e OC_PASS='<temp>' -u www-data nextcloud php occ user:add --password-from-env --display-name "<Name>" <username>`. Hand each person their username and temporary password once; they change it after first login.
4. TOTP enrolment, live (**question 6**): `occ app:enable twofactor_totp`, then for each person and once for the admin account: an authenticator app on the phone, Settings, Security, TOTP, scan, type the code, save the backup codes.
5. Only after everyone is enrolled: `infra/nextcloud/nextcloud-2fa-enforce.sh --check`, then without `--check`. It refuses while anyone is unenrolled.
6. **The single sign-on.** Nextcloud is the identity provider and oauth2-proxy guards every gated subdomain with it.
   - On the VM: `infra/nextcloud/oidc-setup.sh`. It enables the `oidc` app, creates the client unless it exists, registers the redirect URI `https://<sub>.<DOMAIN>/oauth2/callback` for every subdomain in `SSO_SUBDOMAINS` (default `auth notulen`; add every gated name the Caddyfile serves behind `oauth2_auth`, such as `deploy`, by setting `SSO_SUBDOMAINS` in config/harness.env and the vault), and writes OIDC_CLIENT_ID and OIDC_CLIENT_SECRET to `/opt/harness/oidc-client.env`, mode 600.
   - Fold those two values into the vault (update pattern), copying them from the VM over ssh into the temp file without printing them, then `rm /opt/harness/oidc-client.env` on the VM. OAUTH2_PROXY_COOKIE_SECRET is already there from phase 3.
   - Pull on the VM and `compose up -d oauth2-proxy caddy`.
   - Adding a gated subdomain later is: add its name to `SSO_SUBDOMAINS`, re-run `oidc-setup.sh` (idempotent), restart oauth2-proxy.
7. Point them at the Nextcloud mobile app, server `https://cloud.<DOMAIN>`.

**Verify**: `--check` reports all enrolled and enforcement on; an anonymous request to `https://notulen.<DOMAIN>` redirects to `auth.<DOMAIN>`, and logging in there with a Nextcloud account and its 2FA code lands back on Notulen.

## Phase 8: Notulen

**Already done?** S3_BUCKET in `/opt/harness/harness.env` is a real bucket and Notulen is healthy in `compose ps`. Then only revisit the keys still `pending`.

1. Create a private bucket: `scw object bucket create name=harness-notulen-<domain with dots as dashes> region=<region>`, reusing an existing one. This step is worker C's whole job in the parallel block.
2. From the vault pen holder, one new version: S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY (a scoped Object Storage key is the better choice; the laptop key works and is a noted hardening), plus step 3's key and step 4's token.
3. **Question 4**, the Anthropic key: "Notulen turns the transcript into minutes with Claude, and the assistant thinks with it, through an API key with its own billing. Get one at console.anthropic.com: Billing (set a monthly limit), then API keys, Create key. Or skip; recordings are still transcribed and saved." Given: ANTHROPIC_API_KEY. Skipped: leave `pending` and say the job shows as failed with a missing-key error and the transcript is kept.
4. **Question 7**, the minutes target. NOTULEN_TARGET_REPO defaults to the repo in `.claude/project.json` and NOTULEN_TARGET_PATH to `business/minutes`. For them to land as commits, GITHUB_NOTULEN_PAT: github.com/settings/personal-access-tokens, fine-grained, that one repository only, Contents read and write. Skipped: minutes stay in Notulen's database.
5. Pull on the VM, `compose up -d notulen`, check it is healthy and `https://notulen.<DOMAIN>` answers through the sign-on.
6. If the key was given, one live test recording: they open Notulen, allow the microphone, talk for a minute, stop, and wait. Watch `compose logs -f notulen` and narrate.

**Verify**: bucket exists, no `pending` left except consciously skipped keys, service healthy, test done or skipped.

## Phase 9: the assistant (optional, fully skippable)

**Already done?** SIGNAL_BOT_NUMBER is set in the vault, the assistant's gateway container is healthy in `compose ps`, and it answered a message. Then skip.

The assistant ships as an empty template: no people, no number, no calendar. This phase wires it to the owner's own Signal number, calendar and file cloud. `apps/assistant/CLAUDE.md` names its containers and its gateway commands; read it before starting, and use its names over the ones below where they differ. Say in two lines what it is: an assistant on Signal that answers from their calendar, their repository and the server's own health, keeps quiet hours, and holds a page until it is worth sending.

1. **Question 8, the Signal number.** Two ways, pick with them:
   - **Link** (simplest, when they already have a phone with Signal they want the assistant to speak as): the signal-cli container prints a link code. `compose exec -T <signal-cli service> signal-cli link -n assistant` prints a `sgnl://linkdevice?...` URI; turn it into a QR code they scan in Signal, Settings, Linked devices. The assistant then speaks as that number.
   - **Register** (a number of its own: a spare SIM or a VoIP number that receives SMS or calls): `signal-cli -a <+E164> register` (Signal usually asks for a captcha first: they solve it at https://signalcaptchas.org/registration/generate.html and paste the `signalcaptcha://` link, which goes in with `--captcha`), then `signal-cli -a <+E164> verify <code>` with the code they received.
   - Put SIGNAL_BOT_NUMBER (the number in `+E164` form) into the vault. Have the owner send the bot one message from their own phone, then read their identity from signal-cli and set SIGNAL_RECIPIENT (their number), SIGNAL_ALLOWLIST (who may talk to it, comma-separated) and SIGNAL_PEOPLE (`<key>=Name:role[:+E164[:language]]`, comma-separated, one per person on the allowlist). Never set SIGNAL_RECIPIENT to the bot's own number.
   - Back up the registration: `apps/assistant/ops/signal_registration_backup.sh` documents what to copy and why; losing it means re-linking.
2. **Question 9, the calendar.** The assistant reads (and with ASSISTANT_AGENDA_WRITE=1, writes) the agenda over CalDAV as one Nextcloud account. Have them log in as that account, Settings, Security, "Create new app password", name it `assistant`, and paste it. Vault: AGENDA_USER and AGENDA_APP_PASSWORD. Settings: AGENDA_BASE_URL (`https://cloud.<DOMAIN>/remote.php/dav`), AGENDA_CALENDARS (the calendars it may read), TEAM_CALENDAR if they share one.
3. **Question 10, GitHub.** GITHUB_ASSISTANT_TOKEN: fine-grained, the harness repository, Contents and Issues read; Issues write only with ASSISTANT_GITHUB_WRITE=1.
4. Settings that need no question: ASSISTANT_NAME (ask nothing; "Assistant" unless they named it), ASSISTANT_TIMEZONE, ASSISTANT_BRIEF_TIME and ASSISTANT_ADVISOR_TIME (morning defaults from the example), OPENCLAW_DAILY_CAP_EUR (keep the example's cap and say the number once).
5. One new vault version for all of it, pull on the VM, `compose up -d` the assistant's services, then follow `apps/assistant/CLAUDE.md` for the gateway's one-time configuration and its tool check. Verify the tools before the channel: a channel on top of a broken tool door only makes the failure harder to read.
6. **One live message.** The owner messages the bot "what is on my calendar tomorrow?" or "is anything down?" while you watch `compose logs -f` for the gateway. A first reply proves the chain: Signal, gateway, tools, calendar.
7. Two sentences to finish: it answers from its tools or says it cannot check, and its personality, its people and its schedules live in the repository, so a change to how it behaves is a commit, not a setting on the server.

**Skipped**: the containers run idle with no number, which costs nothing but memory. Record it in the phase 12 note.

**Verify**: SIGNAL_BOT_NUMBER in the vault, gateway healthy, the tool check passes, one message answered; or consciously skipped.

## Phase 10: fast transcription (GPU_ENABLED=1)

**Already done?** GPU_ENABLED=1 and KUBECONFIG_B64 is set in the vault, `scw k8s cluster list name=harness` shows a cluster, and the worker image tag is in the registry (`scw registry image list name=notulen-worker region=<region> -o json`, then `scw registry tag list image-id=<id> region=<region> -o json`). Then skip.

`infra/gpu/CLAUDE.md` and `infra/gpu-jobs/` hold the scripts this phase names; read the overlay first. **Never probe state by running the build script**: when the tag is absent it creates a paid build instance. A state check must not be able to spend money.

Before creating anything, the money story in two sentences: the GPU bills only while it works on a recording, cents per meeting; the cluster's control plane is free.

1. Start the image build first, it is the long pole: run the build script from `infra/gpu/` in the background, logging to `/tmp/harness-gpu-build.log`. It pushes `rg.<region>.scw.cloud/<namespace>/notulen-worker:<tag>`.
2. The cluster is phase 4a's; its `gpu` pool role gives the GPU pools (min 0, with stock fallbacks across zones). Use the GPU picker in `infra/gpu/` to choose `POOL_GPU_TYPES` when the default has no stock, then rerun `infra/cluster/create-cluster.sh --apply`. Put the role's pool names (`python3 -m infra.cluster.pool_fallbacks --pools`) in GPU_POOL. No stock anywhere: stay on CPU, say what that means (a one-hour meeting takes hours instead of minutes), record it, skip the rest.
3. Install kubectl on the laptop if missing (release binary into `~/.local/bin`).
4. When the cluster is ready, fetch the admin kubeconfig to a temp file for your own kubectl use. It is NOT the one the server gets.
5. The namespace (GPU_NAMESPACE) and its secrets, from the vault values: a registry pull secret, and ONE generic Secret holding the worker's environment (DB_URL_OPS or the external database URL, S3_*, ANTHROPIC_API_KEY). The Job template mounts it by `secretRef`; never put a credential inline in a Job.
6. Mint the server's own narrow kubeconfig with the script in `infra/gpu/` (a service account that manages transcription Jobs in that namespace only) and base64 it: that is KUBECONFIG_B64. Never print it.
7. Vault, one version: GPU_ENABLED=1, KUBECONFIG_B64, GPU_NAMESPACE, GPU_POOL, NOTULEN_WORKER_IMAGE, SCW_REGISTRY, and POSTGRES_BIND_ADDRESS=0.0.0.0 when the workers reach the server's database over the internet. Say that last one honestly: the database port is then reachable from the internet with the long random password as its guard, because GPU nodes get a fresh address every boot. Pull, `compose up -d postgres notulen`.
8. Wait for the build log's last line (the pushed image) before testing.
9. One short test recording; watch `kubectl get jobs -n <namespace> -w`: a Job appears, a node boots (3 to 5 minutes the first time), the Job completes, the recording finishes. If dispatch fails, the CPU path still processes it; investigate before calling the phase done.

If any step fails twice on the same error: stay on CPU, tell them what that means, record it in the phase 12 note.

**Verify**: image in the registry, cluster ready, KUBECONFIG_B64 in the vault, one recording processed through a Job, or the CPU fallback recorded.

## Phase 11: video calls and recording (optional, fully skippable)

**Already done?** `MEDIA_PUBLIC_IP` and `OPENCLAW_TALK_BOT_ID` are set, `https://signaling.<domain>/api/v1/welcome` answers, and `ASSISTANT_VIDEO_CALL=1`. Then skip. Needs phase 9: the assistant creates the call rooms.

What it gives them, in two sentences: the assistant can put a video call on everyone's calendar with one link and remind them on Signal before it starts, and every such call is recorded and written up as minutes like a Notulen recording. It costs a second server running all month (`PRO2-XS` class), because calls need a wide UDP port range the main server should not carry.

Read `infra/media/CLAUDE.md` first; the scripts there do the work.

1. Say plainly before starting: a recorded call must be announced to the people in it. The room gets a notice when recording starts; telling them beforehand is the organiser's job.
2. `infra/media/provision.sh`. DNS A records `signaling` and `recording` to the IP it prints (as in phase 5).
3. One vault version: `MEDIA_PUBLIC_IP`, and the six `TALK_*` secrets from `config/vault.env.example`, each generated (`openssl rand -hex 32`; the two session keys exactly 32 and 16 characters). Never print them.
4. `infra/media/deploy.sh <ip>`, in the background (it builds Janus and the recorder, several minutes). Wait for `https://signaling.<domain>/api/v1/welcome` to answer.
5. On the main server: `ssh harness@<SERVER_IP> /opt/harness/repo/infra/media/connect-talk.sh`. Put the bot id it prints in `OPENCLAW_TALK_BOT_ID` and set `ASSISTANT_VIDEO_CALL=1` and `ASSISTANT_MEETING_REMINDERS=1`, one vault version, then wait one deploy cycle.
6. A test, if they have five minutes: ask the assistant on Signal for a video call now with themselves; open the link, talk for over five minutes (shorter calls are skipped), hang up. Minutes appear in Notulen a few minutes later.

**Skipped**: the assistant makes no call links and no call is recorded. Record it in the phase 12 note.

## Phase 12: finish

1. Write a memory note in `.claude/memory/` (a short file plus one index line in MEMORY.md): domain, server IP, region, instance type, bucket, cluster and registry if the GPU tier ran, the media box IP if phase 11 ran, which phases ran, what was skipped and why, the assistant's number if one was set up, the expiry date of the harness-vm API key, and the date. No passwords in memory, ever.
2. Print the addresses on their own lines: the root, `cloud.`, `notulen.`.
3. The daily loop in four lines: open a terminal, run `claude --dangerously-skip-permissions` in this folder, say what you want in plain words, and after I push to main the deploy gate tests the change and it goes live in a few minutes.
4. Bigger work, in three lines: I first ask questions, then write the plan as an issue on their GitHub page, then build it. Show the issues address once: `gh repo view "$(git remote get-url origin)" --json url --jq .url` plus `/issues`.
5. If anything ever looks broken, they say "something is broken" and the troubleshoot skill takes over.

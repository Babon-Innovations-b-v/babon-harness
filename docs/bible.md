# The bible

The single source of truth for how this system works. One file, chaptered. A chapter ID is the
slug after the `##` (for example `architecture/system-context`), and the chapter map in root
[`CLAUDE.md`](../CLAUDE.md) points at it; link to a chapter as `docs/bible.md#architecturesystem-context`.

**How to use it.** Read the chapter the work touches, never the whole file. When you learn
something load-bearing that a future reader would otherwise have to re-derive from code, write it
into its chapter in the same session. When a chapter contradicts the code, the code wins and the
chapter gets fixed on the spot.

**What does not go here.** Vocabulary goes in [`CONTEXT.md`](../CONTEXT.md). Decisions that were
hard to reverse go in [`docs/adr/`](adr/). Status of ongoing work goes on its GitHub issue. The
bible holds how the thing works, not what we are doing about it.

**Budget.** 900 words and 8 sections per chapter; `.claude/hooks/local/bible_guard.py` blocks an
edit that grows a chapter past either without a line starting `Budget:` saying why. A drawn
module's boxes are each claimed by one piece of text here carrying its ◈ marker, and
`docs/diagrams/tools/linkmap.py` fails on a box nothing claims.

---

## architecture/system-context

What the harness is: one repository that holds a small company's whole working system, and the
loop a person and Claude Code use to change it. Push to `main` is the deploy.

### The pieces

```
laptop: Claude Code in this repository
  GitHub: main, issues, the board
    the server: one Scaleway VM, the compose stack behind Caddy
      Nextcloud: files, calendar, the single sign-on
      Notulen: meetings in, minutes out
      the assistant: Signal in and out
      observability: Prometheus, Alertmanager, probes
    Scaleway: object storage, Secret Manager, optional GPU cluster
```

Nothing deploys from the laptop. Work lands on `main`, the server pulls it, the deploy gate tests
the commit against its own tree, and only a green commit is swapped in. A red one holds the old
version, and with `EJECT_ENABLED=1` it is reverted on `main` and handed back to its author.

### Who talks to it

| Who | Through | Reaches |
|---|---|---|
| The owner and the team | a browser, one Nextcloud login | files, calendar, Notulen, gated pages |
| The owner and the team | Signal | the assistant |
| A session | git and `gh` | the repository, issues, the board |
| The public | HTTPS | the website at the root domain |

Every name is a subdomain of `DOMAIN`. Caddy terminates HTTPS for all of them. A gated name sends
an anonymous browser through oauth2-proxy to Nextcloud, which is the identity provider, so one
login with its 2FA code opens everything.

### Where configuration lives

| Place | Holds | Written by |
|---|---|---|
| `.claude/project.json` | the GitHub side: repo, board, people | `.claude/scripts/setup-github.py` |
| `config/harness.env` | non-secret settings | the owner, from `config/harness.env.example` |
| the vault | the full environment, secrets included | `infra/secrets/push-env.sh` |

Nothing else is read. The vault is one Scaleway Secret Manager secret (`VAULT_SECRET_NAME`); the
server pulls it every deploy cycle to `$HARNESS_ROOT/harness.env`, mode 600. Scaleway API keys
stay in the laptop's `scw` config. The `onboard` skill takes a fresh laptop to a running server
and fills all three.

### What is not in it

No business content, no customer data and no person's name ships with the repository. The
assistant starts empty and is wired to the owner's own Signal number, calendar and file cloud
during onboarding. Minutes, memory notes and the people list are written into the owner's own
private copy as they happen.

## apps/assistant

### What runs

| Container | Image | Job |
|---|---|---|
| `assistant-gateway` | upstream OpenClaw, pinned | holds the Signal conversation, the sessions and its own memory |
| `assistant` | built from `apps/assistant/Dockerfile` | the door: alert triage, the notify pen, patrol, the MCP tool door |
| `signal-cli` | signal-cli-rest-api, pinned | the Signal account both of them use |
| `assistant-whisper` | speaches, profile `voice` | turns a voice note into text |

The gateway is someone else's software, run unmodified. It answers people. The door is this repository's code, and it decides what reaches a phone. Neither container is reachable from the internet: the gateway and the door publish only on the server's loopback, and Alertmanager, Prometheus and the gateway reach the door by its name, `assistant`, on the compose network. The door keeps its memory in one SQLite file on a named volume and runs a single worker, because that file has one writer.

### How an alert reaches Signal

```
Alertmanager
  -> POST /webhook/alertmanager    (bearer OPENCLAW_WEBHOOK_SECRET)
  -> triage                        (the model reads, then pages or stays silent)
  -> the notify pen                (pages held and batched)
  -> the flush                     (quiet hours, mutes, one message)
  -> signal-cli /v2/send
```

Triage gives the model the alert and its read-only tools, and asks for one decision: page, enrich or stay silent. A page then waits in the notify pen, so a burst of related alerts leaves as one message. Night-time warnings wait for the morning, and a critical page leaves at any hour.

Every sentence crosses the claim guards before it is sent: a sentence about live state that no tool read this pass is dropped, and so is a command for the reader to type. Every send is written to the state database, and the chat relay copies it into the recipient's own gateway session, so a reply in chat has the context it answers.

### The tool door

The gateway calls the door at `http://assistant:8000/mcp` for every tool that touches the team's systems. The read tools are the calendars, the board, Prometheus, Loki when `LOKI_URL` is set, the ops database, the bible, deploy status, the repository's documents and the assistant's own memory. The write tools are the calendar, video calls, the board, a message to a teammate and the assistant's memory.

Each write has its own switch, needs `requested_by` naming the person who asked, and is recorded in the action log before it runs. A tool whose configuration is missing is not offered at all. A tool that ran and failed says so, and never comes back as an empty answer.

### The workspace

| File | Rendered from |
|---|---|
| `AGENTS.md` | the principles the owner taught and the tool list |
| `SOUL.md` | the repository's `.claude/soul.md` |
| `USER.md` | the people registry and each person's own rules |
| `IDENTITY.md` | the assistant's name |

The gateway builds its system prompt from these four files. `apply.sh` renders them from the live door on every deploy. The same pass applies the gateway's config fragment and declares two scheduled reports, a weekday brief and a Monday advisor, at the times the owner set. Both reports leave through `message_teammate`, where the word cap is a number in code. A file the assistant edits by hand is gone at the next deploy, which is the point: the doctrine has one home.

### What the owner fills

| Where | Keys |
|---|---|
| `config/harness.env` | `ASSISTANT_NAME`, `ASSISTANT_TIMEZONE`, `ASSISTANT_BRIEF_TIME`, `ASSISTANT_ADVISOR_TIME`, the write switches, `AGENDA_BASE_URL`, `AGENDA_CALENDARS`, `TEAM_CALENDAR` |
| the vault | `SIGNAL_BOT_NUMBER`, `SIGNAL_ALLOWLIST`, `SIGNAL_PEOPLE`, `SIGNAL_RECIPIENT`, `AGENDA_USER`, `AGENDA_APP_PASSWORD`, `GITHUB_ASSISTANT_TOKEN`, `OPENCLAW_WEBHOOK_SECRET`, `OPENCLAW_GATEWAY_TOKEN` |
| `.claude/project.json` | the repository it works on, the people's GitHub logins, the board's areas |

The assistant ships empty: no people, no memory, no knowledge beyond one example note. Before the first start, link the bot number to signal-cli once with `SIGNAL_CLI_MODE=native`, then set it back.

## apps/notulen

### The recording path

```
phone browser -> 5 s chunks -> /api/upload/chunk -> /tmp/notulen/<job>/audio.webm
stop -> /api/upload/finalize -> stitch -> loudness boost -> S3 -> process_job
```

The recorder is a single page at `notulen.$DOMAIN`, behind the Nextcloud single sign-on. Pressing record opens a row in `notulen_jobs` with status `recording`. From then on the browser sends five seconds of audio at a time. Each piece is kept in the phone's IndexedDB until the server confirms it, so a locked screen or a closed tab loses nothing. The next visit offers "Resume upload".

The server appends the pieces to one file on a volume, so a redeploy does not wipe a meeting in progress. Gates refuse a chunk out of order (409 asks the browser to re-send from the gap), a chunk over 10 MB, a recording under 10 KB, and a third concurrent job.

When the microphone dies mid-meeting, the page beeps, vibrates and keeps asking for it; recording resumes into the same session. At finalize the server stitches the pieces and boosts a near-silent recording. The audio goes to S3 before any check that could end the session, so every failed job can be retried.

### Transcription and minutes

| Tier | When | Transcribes with | Speaker labels |
|---|---|---|---|
| GPU | `GPU_ENABLED=1` and `KUBECONFIG_B64` set | whisper-large-v3 in a Kubernetes Job | yes, with `HF_TOKEN` |
| CPU | otherwise, or when GPU dispatch fails | whisper `medium` in the dashboard | no |

Either tier ends the same way. Under 50 words is `no_speech`. Under five minutes is `too_short`, and its transcript is kept. Otherwise Claude fills `inputs/notulen_template.md` in the meeting's language, and the row becomes `committing`.

The prompt names a speaker only when the audio proves who it is; otherwise the minutes say "Speaker 1". The GPU worker is a separate image that imports nothing from the dashboard, so the prompt, the floors and the attendee cleaning are written twice. Tests keep the two copies in step.

### Committing and correcting

```
committing -> GitHub Contents API -> complete
<NOTULEN_TARGET_PATH>/<YYYY-MM>/<alice_bob>/<YYYY-MM-DD>.md
```

`complete` means the file is in `NOTULEN_TARGET_REPO`, committed with `GITHUB_NOTULEN_PAT`. A loop retries every 30 seconds with no time limit, and pages the assistant once an hour when minutes have waited more than 15 minutes.

A second meeting on the same day lands on `-2`; nothing is ever overwritten except by a person's correction. The editor saves over the committed file with the version it read, so two people editing at once collide instead of losing an edit. Deleting a recording removes the audio, the row and the file.

### Handing on to the assistant

- a recording that stopped sending audio for 90 seconds
- a GPU job Kubernetes failed
- a GPU dispatch that fell back to CPU
- minutes stuck uncommitted

Every page this dashboard raises goes to the assistant's `/webhook/notify`, never straight to a phone. The "Send to the assistant" button posts the corrected minutes to the assistant's `/webhook/notulen`, which opens or updates the issues for the action items and returns their numbers. The button fires once: the claim is written before the call, and given back only if the request never arrived.

### Who is in the room

The page knows the signed-in person (`Remote-User`, else `Remote-Email`) and the `NOTULEN_ATTENDEES` list, offered as chips. Anyone else is typed in. The same name in two spellings counts as one person, because the number of attendees is what the GPU worker uses to fold stray voices back into real ones.

## apps/documents

### What it makes

| Input | Output |
|---|---|
| a YAML data file | an A4 PDF in the house style |
| `design/tokens.css` | colors, fonts and spacing, injected as CSS variables |
| `design/company.yaml` | the issuing company block: name, address, IBAN, registration and VAT numbers |

`python -m documents <type> --data file.yaml --out file.pdf` renders `templates/<type>/template.html` with Jinja2 and turns it into a PDF with WeasyPrint. `--sample` renders the type's bundled `sample-data.yaml`, which uses only placeholder names. The invoice is the reference type; a new type is a copy of its folder, adapted.

Template CSS uses only design variables (`var(--color-primary)`, `var(--font-body)`), so every document follows a restyle of `design/`. Field labels have English defaults; an optional `labels:` map in the data file translates them, so one template serves any language. Data values are HTML-escaped. An empty company profile renders cleanly, without dangling "IBAN" or "Reg. no." lines.

### What it needs

WeasyPrint loads pango, pangoft2, harfbuzz and fontconfig at import time. When they are missing, the error names the apt packages to install. One test renders a real PDF and reads it back with pypdf; it skips with that same install line when the libraries are absent.

### Sending

`infra/email/send_document.py` sends one email, optionally with the PDF attached, through Scaleway's Transactional Email API, because Scaleway blocks outgoing SMTP. It reads `TEM_PROJECT_ID`, `TEM_FROM` and `TEM_REGION` from the environment or the harness env file, and the secret key from `SCW_SECRET_KEY` or the `scw` CLI. It has no default project. Nothing is sent without the owner seeing the document and saying yes.

## apps/website

### What it serves

```
browser -> Caddy (HTTPS, bare domain) -> website:80 (nginx) -> apps/website/ + /design/
```

The public site is static files in `apps/website/`, served by a stock `nginx:alpine` image. The Dockerfile sits beside the page and builds from the repository root, so it can copy both the page and `design/`. The page links `/design/index.css` and nothing else from the design system, so a change to `design/tokens.css` restyles the website, the documents and the dashboards together. The company profile and the build files are removed from the image, so they are never served.

### How it changes

Edit `apps/website/index.html`, or add pages and images beside it, and push to `main`. The deploy cycle rebuilds the `website` service, defined in `apps/website/compose.yml` and included by the root `docker-compose.yml`, within about two minutes. A healthcheck fetches `/` every 30 seconds.

### design/

| File | Holds |
|---|---|
| `tokens.css` | the values: `--color-*`, `--font-*`, type scale, spacing, radii, shadows, status colors |
| `base.css` | plain HTML defaults plus `.lead`, `.muted`, `.eyebrow` |
| `index.css` | the one entry point, importing the two above |
| `company.yaml` | the company profile, every field empty until onboarding fills it |

Brand colors appear in both `company.yaml` and `tokens.css`, and onboarding keeps them in sync. A custom font is a `.woff2` in `design/` plus an `@font-face` block in `tokens.css`; until then the system font stack is used.

## infra/platform

### One login across subdomains

| Host | Goes to | Login |
|---|---|---|
| `DOMAIN` | website | public |
| `cloud.DOMAIN` | Nextcloud | Nextcloud's own, password and second factor |
| `auth.DOMAIN` | oauth2-proxy | sign-in and sign-out pages |
| `notulen.DOMAIN` | notulen | single sign-on |
| `deploy.DOMAIN/hooks/*` | webhook service on the host | HMAC signature, no login |

Caddy is the only container with public ports. It gets certificates from Let's Encrypt on its own once DNS for these names points at the server.

Nextcloud is where accounts live. You create a person there, they set a password and enrol an authenticator app, and from then on that one account opens every private subdomain. Nextcloud's oidc app makes it an identity provider; oauth2-proxy is the client that logs in against it.

On every request to a private subdomain, Caddy asks oauth2-proxy whether the browser carries a valid login cookie. Yes means Caddy forwards the request with the person's account id in `Remote-User` and their email in `Remote-Email`. No means a redirect to Nextcloud and back. Caddy first deletes any `Remote-User` the browser sent itself, so an app can trust the header.

The cookie is set on `.DOMAIN`, so one login covers every subdomain. It lasts 8 hours and is never refreshed. The Nextcloud session behind it lasts 7 days, so when the cookie runs out the browser is signed straight back in, and Nextcloud checks on the way that the account still exists. A disabled account loses access within 8 hours.

Adding a private subdomain: a Caddyfile block that imports `oauth2_auth`, the name in `SSO_SUBDOMAINS`, and a run of `infra/nextcloud/oidc-setup.sh`. Two-factor login is enforced for everyone once `NEXTCLOUD_2FA_ENFORCE=1`; the script refuses while any account has no second factor, because that account would be locked out.

### The vault

```
laptop: config/harness.env + secrets   (a private file)
  -> infra/secrets/push-env.sh          (scw CLI, new version)
  -> Secret Manager secret harness-env
  -> infra/secrets/pull-env.sh          (server, every deploy cycle)
  -> $HARNESS_ROOT/harness.env          (mode 600)
  -> docker compose --env-file
```

All configuration is in three places. `.claude/project.json` names the GitHub repository and the people. `config/harness.env` holds settings that are not secret, such as the domain and the region. The vault is one Scaleway Secret Manager secret holding the whole environment: those settings again, plus every password and token listed in `config/vault.env.example`.

Each change is a new version of that secret. The server pulls the latest version every deploy cycle, so a pushed change is live a few minutes later without logging in to the server. If the pull fails, the server keeps the file it already has and the stack carries on.

The Scaleway keys themselves are not in the vault. The laptop uses the key from `scw init`. The server has its own key, allowed to read this one secret, in `$HARNESS_ROOT/scw-secrets.env`, which onboarding writes once and git never sees.

### The shared library

| Piece | What a dashboard gets |
|---|---|
| `make_dashboard_app` | a FastAPI app with an activity log, AI-call costs, health checks and a sync heartbeat already wired |
| `get_user(headers)` | the signed-in account from `Remote-User`, or `anonymous` |
| `get_db()` | a connection to the stack's Postgres, or None when it is down |
| `call_claude` | the one way to call Claude; every call is logged with tokens and cost |
| `/static/dashkit/*` | shared JavaScript and `base.css` |

dashkit lives in `lib/dashkit` and every dashboard is built on it. A dashboard keeps working when the database is unavailable: the activity log comes back empty and health checks answer 503, but nothing crashes. Activity and cost logging never break the feature being logged. Table names reach SQL only after a check that they are plain lowercase identifiers. `base.css` takes its colours and fonts from `design/tokens.css`, so restyling every dashboard is an edit to the tokens file.

## infra/deploy

```
push to main -> webhook -> cycle: lock -> fresh -> pick one commit -> export -> gate -> build -> boot -> bookmark
                         -> lane:  every queued commit, each in its own tree -> verdict
```

### The loop

Pushing to `main` is the deploy. On the server, `harness-auto-deploy.timer` runs `infra/auto-deploy/auto-deploy.sh` every two minutes, and the push webhook starts it at once. A cycle takes the lock, fast-forwards the clone, and picks ONE commit past the deploy bookmark (`/var/lib/harness/last-deployed-sha`): the newest commit that already has a green verdict for its exact tree, otherwise the next one. It is never the tip and never a batch, because a red on a batch names nobody's commit.

The commit is exported with `git archive` into a tree of its own. The gate tests that tree, and the images are built and started from it, never from the clone the webhook keeps moving. `docker compose` rebuilds only the services whose fragment folder changed, then checks that each one boots: healthy if it has a healthcheck, still running after 20 seconds if not. A service that does not boot is rolled back to the image and tree it ran before. The bookmark moves only when everything shipped.

Each stage reports on the commit's GitHub page as `vm/gate`, `vm/build`, `vm/boot` and `vm/deploy`. `failure` means the stage ran and said no; `error` means it could not form an opinion. The repository's only workflow opens an issue when those reports stop.

### The gate and its three verdicts

| Verdict | What it means | What happens |
|---|---|---|
| green | pytest exited 0 | cached for this commit, scope and tree; ships |
| red | the run happened and said no | nothing ships; a failing test run is cached |
| amber | the run could not start or finish | nothing ships; never cached, never reverts anything, retried next tick, alerts after three |

Red covers a failing test, code that would not load, a run that collected nothing, a test with no register row, and a test that still passes with its own break applied. Amber covers a failed `uv sync`, a timeout, a missing interpreter and a killed run. Both ship nothing, because a gate that could not run must never look like a gate that passed.

The gate does not run the whole suite for every commit. `tools/gate_scope` follows the import graph and the register's triggers to pick the tests a change can reach; anything it cannot reason about runs the full suite. Narrowing is licensed only while the nightly unselected run (`harness-gate-audit.timer`) is green. With no green run in 48 hours, or one test it proves the narrowing missed, every commit runs the full suite again.

A verifying lane (`commit_gate/`) runs the gate on every queued commit ahead of the cycle, each in its own tree and environment, so when the cycle reaches a commit its verdict is usually already there.

### The register

Every test has one row in `tools/test_register/_rows.py`: the module the test pins, the changed paths that select it, and the break, an exact edit to a source file that must turn the test red. `python3 -m tools.test_register --new <module> --says "<invariant>"` writes a test and its row together. The gate refuses a tree whose tests and rows disagree. After a green suite it applies the break of every row the commit touched and reruns that test; a test that still passes is red. A test that can never fail looks exactly like a good one, and this is what tells them apart.

### The eject

The eject takes a rejected commit back off `main` and hands it back to its author. It ships off (`EJECT_ENABLED=0`). While it is off, a red holds the queue, and the server alerts that a person must fix or revert the commit.

Armed, it reverts exactly one commit. It never reverts its own commits, never more than one per commit, and only when the commit's parent is known good. The work goes back on a branch `auto-eject/<sha>` with a draft pull request. Never press merge on it: the branch opens with the tree the gate refused. Fix it there and land it on `main` as one squashed commit.

## infra/observability

### Alert path

```
Prometheus (rules, every 30 s)
  -> Alertmanager (groups, repeats: critical 1 h, warning 4 h)
    -> alert-relay
      -> assistant /webhook/alertmanager -> triage -> Signal
      -> or, while the assistant-down flag is fresh: signal-cli /v2/send -> SIGNAL_RECIPIENT
```

Prometheus scrapes itself, Alertmanager, node-exporter and the blackbox exporter, and probes every subdomain in `PROBE_SUBDOMAINS` over HTTPS. When a rule fires, Alertmanager posts the group to the alert-relay, which hands it unchanged to the assistant. The assistant decides what reaches the phone and how it is worded. Severity changes how often a still-firing group is repeated; it never decides whether it is delivered.

### Rules

| Alert | Fires when | Severity |
|---|---|---|
| TargetDown | a scrape target is down for 5 minutes | critical |
| EndpointDown | an HTTPS probe fails for 5 minutes | critical |
| DiskAlmostFull | a filesystem is over 85 percent for 10 minutes | warning |
| MemoryPressure | under 10 percent of memory is available for 10 minutes | warning |
| ContainerRestarting | a container restarts more than twice in 15 minutes | warning |
| UnitFailed | a `harness-*` systemd unit is failed | warning |
| TextfileCollectorStale | the collector has not run for 10 minutes | warning |
| DeployLoopStale | no successful deploy cycle for 6 hours | warning |
| CertificateExpiring | a certificate expires within 14 days (3 days: critical) | warning |

Every rule writes a summary and a `first_action` naming the command to run. The deploy loop proves it is alive by writing `harness_deploy_last_success_timestamp_seconds` into the textfile directory after each good cycle.

### Deadmen

| Job | Every | Watches | Pages when |
|---|---|---|---|
| `harness-assistant-deadman` | 60 s | the relay's `/assistant-check` | 3 failures in a row |
| `harness-gateway-deadman` | 60 s | the assistant's Signal gateway health route | 3 failures in a row |
| `harness-dead-mans-switch` | 15 min | the Watchdog alert in Alertmanager | unseen for an hour |
| `harness-signal-send-canary` | 30 min | the bot sending a message to itself | it tells you once sending works again |

A watcher cannot report through the thing it watches, so every deadman page goes straight to signal-cli, never through the assistant. Three misses, about three minutes, count as down; one miss is usually a restart. A down page goes out once and repeats at most hourly.

The assistant deadman asks the relay rather than the assistant, because the relay is the road an alert travels. Healthy means both: the assistant's `/health` answers, and the assistant accepts the relay's bearer on an empty alert envelope. An assistant can answer `/health` while refusing every delivery with a 401, and that has to count as down.

### Raw road

When the assistant deadman sees three failures it writes `/var/lib/harness/assistant-down`, rewritten every minute while the outage lasts. While that file is at most 300 seconds old, the relay stops forwarding and sends each alert group to Signal itself: one plain message per group, the same group at most once per half hour. An older flag means the deadman stopped writing, so the relay treats the assistant as up.

The Watchdog alert fires constantly and Alertmanager routes it nowhere. If Prometheus, a rule file or Alertmanager breaks, the Watchdog stops being refreshed, and the dead-man's switch pages from outside the pipeline.

### Unit failures

Every `harness-*` timer job carries `OnFailure=harness-notify-failure@%n.service`. A failure sends one Signal page with the unit name, the last line the failing run wrote, and its journal tail. The same failure is held for 12 hours; a different failure of the same unit pages at once. The Signal canary's own failure is not sent over Signal, and `harness-assistant*` failures stay quiet while the assistant-down flag is fresh.

### Where it runs

| Piece | Where |
|---|---|
| prometheus, alertmanager, node-exporter, blackbox-exporter, alert-relay | `infra/observability/compose.yml` |
| deadmen, canary, textfile collector, failure pager | systemd units, installed by `infra/observability/systemd/install.sh` |
| state, flag, textfile metrics | `/var/lib/harness` |

Everything is published on loopback only: Prometheus 9090, Alertmanager 9094, relay 9095. Read Prometheus through an SSH tunnel.

## infra/gpu

### What the tier is

```
dashboard -> KUBECONFIG_B64 -> GPU cluster, namespace $GPU_NAMESPACE
record pressed -> placeholder Pod (holds a GPU)
recording done -> notulen Job (preempts it) -> worker writes row -> dashboard commits
```

The GPU tier is optional. Without it notulen transcribes on the server's CPU, which takes hours for a long meeting; with it a meeting takes minutes. It is a Scaleway Kapsule cluster with one or two GPU node pools that scale to zero, so a node bills only while it transcribes.

The dashboard talks to it with its own service account. The worker writes its result straight into the stack's Postgres, which therefore listens beyond the server (`POSTGRES_BIND_ADDRESS=0.0.0.0`), with the database password as the only guard.

### The pieces

| Piece | Where | What it does |
|---|---|---|
| Worker image | `infra/gpu/Dockerfile` | pyannote, whisper-large-v3, Claude; public pytorch base |
| Builder | `infra/gpu/build-worker.sh` | builds on a temporary instance in the region, pushes to the registry namespace `SCW_REGISTRY` |
| Stock finder | `infra/gpu/pick-gpu.sh` | first GPU type with stock, cheapest first, across zones |
| Cluster objects | `infra/gpu/apply.sh`, `k8s/` | namespace, service account and Role, PriorityClass, worker Secret, ConfigMap, pull Secret |
| Dashboard key | `infra/gpu/make-dashboard-kubeconfig.sh` | a kubeconfig with a static token, base64 into `KUBECONFIG_B64` |
| Job code | `infra/gpu-jobs/gpu_jobs` | builds and posts the Job and the placeholder |

### Turning it on

1. Create a cluster with one GPU pool named `$GPU_POOL`, autoscaling from zero, tainted `workload=notulen:NoSchedule`.
2. Run `build-worker.sh v1` and put the printed image in `NOTULEN_WORKER_IMAGE`.
3. Set `DB_URL_OPS` and the Postgres bind, then run `apply.sh`.
4. Put the kubeconfig in the vault and set `GPU_ENABLED=1`.

### Waiting for a GPU

A GPU node can take half an hour to start when its zone is short of cards. Pressing record therefore submits a placeholder Pod at the `notulen-gpu-warmup` priority (-5). The autoscaler starts a node during the meeting, and the real Job takes the placeholder's place by preemption when the recording ends. The placeholder ends itself after six hours.

The Job has no deadline of its own, so a meeting waits out a stock-out instead of being killed while still waiting. The worker's run is capped at four hours once a node accepts it. A second pool in another zone, listed in `GPU_POOL`, gives a meeting somewhere else to go.

### Credentials

No credential is ever written into a pod. The worker reads the database URL, the Anthropic key, the S3 keys and the optional Hugging Face token by reference to the `notulen-worker-secrets` Secret, which `apply.sh` builds from the vault copy at deploy time.

The dashboard's account may only create, list and delete Jobs and Pods in its own namespace. `MAX_DAILY_JOBS` (50) caps how many Jobs a day can start.

### What can go wrong

- A dispatch that fails falls back to CPU and pages once an hour.
- A Job Kubernetes marks failed is caught within a minute: its row is failed and the assistant is paged.
- A dashboard restart leaves running Jobs alone.
- A node that comes up without a usable GPU points at the provider's NVIDIA driver, not this code.

## workflow/loop

One task is one conversation, from "I want this" to production without leaving the chat: grill,
to-prd, code, close.

### Where a turn starts

| Way in | What it is |
|---|---|
| A new idea | something not there yet |
| A person using it | what they found by hand |
| A page from the assistant | the watch, no person |

Nothing has to be broken and no ticket exists first: the issue is written later in the turn. All
three arrive as one messy prompt: pasted conversations, screenshots, links. A page of thinking
rather than a task goes to `/brain-dump`, which sorts it into claims, questions, decisions and
vision. An effort too big and too foggy for one session goes to `/wayfinder`, which charts it as
a PRD whose route is unknown.

### Nothing is built before this

| What is read | Where |
|---|---|
| The glossary | `CONTEXT.md` |
| The bible chapter | `docs/bible.md` |
| The area overlays | `<area>/CLAUDE.md` |
| The decisions | `docs/adr/` |
| Prior issues | GitHub, open and closed |

The `grill` skill forces those reads before the assistant answers, and what comes back is one
question, not a summary; a session remembers nothing of the last one. **Facts are looked up, never
asked.** What reaches the person is judgment, taste, priority and risk.

**Whatever settles is written down at once**: a term in the glossary, a trade-off on its issue or
as a proposed ADR, an invariant in its chapter. The plan leaves the chat as a GitHub issue written
like a PRD (`to-prd`); conversations are throwaway, the issue outlives them, and the board over it
is where work is tracked.

### Write it, cut the old, prove it

```
one commit, straight on main
  the code
  the module's drawing
  the bible text claiming each box
  minus what it replaces
  plus the test that pins it, with its register row
```

No branch and no pull request keeps a task in one conversation and leaves no review queue
(ADR-0001). A session that writes files works in its own worktree, set up with
`bash .claude/scripts/worktree-setup.sh`, and pushes with `git push origin HEAD:main`. The drawing
and the chapter are written in the same pass as the code, through the `diagram` MCP and the
`case-study` skill, and linked into the issue only when a human is needed.

**Dead code is a defect, not an archive.** A module exists only while deleting it would scatter
real complexity across its callers.

### What stops a bad commit

| Check | Where | When |
|---|---|---|
| The torn-commit guard | `.claude/hooks/pre-commit` | every commit |
| The test register and break replay | `.claude/hooks/local/pre-commit` | every commit |
| The `audit-*` skills | a session | before a push that matters |
| The deploy gate | the server | every commit on `main` |

A test and the change that makes it pass go in one commit: the gate runs every commit against its
own tree, so a test that arrives one commit before its fix is red for ever. A red sends the turn
back to building.

### After the push

| What runs | Cadence | What stops without it |
|---|---|---|
| auto-deploy on the server | a short timer, plus a push webhook | nothing ships |
| The eject, `EJECT_ENABLED=1` | on a red gate | bad commits stay on main |
| A person on the page | per change | nobody says it is right |
| The assistant on Signal | around the clock | production runs unwatched |

Pushing to main is the whole deploy interface. GitHub Actions never build or test; the server
posts its own commit statuses, so the commit page shows what was verified, built and made live.
The tests answer whether it broke; the person answers whether it is right, reading the drawing
against the code. What they find becomes the next messy prompt.

### Tuning Claude

- **Friction**: Claude gets something wrong for this team.
- **Rule**: the correction goes into `.claude/soul.md` or the root `CLAUDE.md`, with a name and a date.
- **Inject**: a `UserPromptSubmit` hook replays the soul rules into every prompt.
- **Behaviour**: the tuned default for everyone here, not just the person who corrected it.

Four mechanisms carry rules, one job each: **skills** (`.claude/skills/`, methodology),
**overlays** (`<area>/CLAUDE.md`, loaded with a directory), **hooks** (`.claude/settings.json` and
`.claude/hooks/local/hooks.json`, firing on a harness event), and **GitHub issues** (the durable
backlog). "From now on, when X" is a hook. The shared files under `.claude/` come from the starter
template and stay identical to it; this repository's own behaviour goes in `.claude/hooks/local/`
and its own skill directories.

### The board, commits and memory

- **Board**: one GitHub project, from `setup-github.py --board`. Status is a column (`LowPriority`, `Not started`, `In Progress`, `Review`, `Done`), set with `.claude/scripts/board-status.py`; triage state is a label.
- **Commits**: imperative and scoped, `module: description`. A subject that needs "and" is two commits.
- **Memory**: linked into `.claude/memory` by `bootstrap.sh` and committed by the `Stop` hook, so it survives a wiped machine. Nothing secret goes in it.

## workflow/module-standard

The house standard for a module, so a reader can predict the shape of code they have not seen
yet. Each rule below is a line an auditor can mark pass or fail.

### Tiers and layout

```
<package>/                  # Tier S: one deep module, up to about 8 files
  __init__.py               # the seam: docstring module map, re-exports, __all__
  <one_concern>.py          # one public callable, helpers _prefixed
  tests/test_<invariant>.py # named for what it pins

<package>/                  # Tier M: a 5-layer deep module
  entrypoints/              # CLI mains and worker loops; config assembled here only
  gates/                    # validation as data: (ok, reasons)
  core/                     # the domain logic
  shared/                   # helpers used by 2 or more layers
  inputs/                   # reference data, declared committed or ignored
```

The tier is declared in the package overlay or docstring. A directory with more than 12 entries is
missing a boundary. No loose files outside the carve-out (ADR-0002). No `sys.path` tricks in
source; a container's import layout is solved in its Dockerfile.

### The interface

- **`__init__.py` is the declared seam**: a docstring module map, curated re-exports, `__all__`. An empty one invites file-path imports.
- **Every implementation file opens with its contract**: what it owns, what it does NOT own and where that lives, and a FAILURE POLICY for anything touching a database, the network or a subprocess.
- **One public callable per file.** Dataclasses, protocols, exceptions and enums in its signature ride with it.
- **Callers import the package**, never a file inside it and never a `_`-prefixed name.

### The implementation

- **One function, one purpose.** A docstring that needs "and" between two concerns is two functions.
- **No single-letter names** outside comprehensions and lambdas.
- **Heavy dependencies import lazily** inside the function that needs them, so the package and its tests import without them.
- **Env vars are read at call time**, not import time, and the config tree is assembled only at the entrypoint; `core/` takes primitives.
- **No DI container.** Collaborators are keyword-only parameters with production defaults; a port is introduced when a second adapter exists.
- **One home per value.** A constant declared twice will drift.

### Tests

```
python3 -m tools.test_register --new <module> --says "<invariant>"
python3 -m tools.test_register --replay <test file>
```

The first writes the test and its register row together; the second applies the row's break and
demands red. Every test has one row, and the row carries an exact edit that must turn the test
red, so a test that cannot fail is caught. A test feeds a known input and checks an answer derived
independently of the code under test, or a property that must hold. It crosses only the public
seam, and its collaborators are injected rather than patched.

### Failure tiers

| Tier | What | Rule |
|---|---|---|
| 1, structural state | database writes, state transitions, money, auth | propagate, fail loud |
| 2, best-effort side effects | alerts, notifications, cleanup | swallow and log, with the reason written at the site |

Fail-open or fail-closed is a named decision per seam, never an accident. A bare `except: pass`
is a finding in either tier. At `gates/`, failure is a return value, not an exception.

### The auditor's checklist

1. Tier declared and matching the tree; no directory over 12 entries.
2. `__init__.py` carries a module map and re-exports, or a written reason it does not.
3. One public callable per file; helpers `_`-prefixed.
4. Every module docstring says what it owns, what it does not, and its FAILURE POLICY.
5. Nothing outside the package imports a `_` name or a file path behind the seam.
6. One purpose per function; no single-letter names.
7. Heavy dependencies lazy; env read at call time; config assembled at the entrypoint only.
8. Every test has a register row whose break turns it red.
9. Tier-1 writes propagate; every Tier-2 swallow has its reason at the site.
10. Overlay, bible and docstring agree with the code; a sanctioned exception is written in both the overlay and the chapter.

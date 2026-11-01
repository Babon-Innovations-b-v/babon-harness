# babon-harness

A small company keeps its whole working system in this repository. That covers how its people
work with a coding agent, the guards that catch the agent's known mistakes, an index of the code,
and the documents and diagrams that explain it. It also covers the company's own services:
meeting minutes, an assistant on Signal, monitoring, and deploys that test each commit first.
Babon Innovations works in it daily. This copy has the company taken out and keeps 29 skills,
15 hooks and 137 test files.

A piece of work starts as a message in Claude Code, often an untidy one. Before anything is
built, the agent reads what the repository already says and asks about the plan one question at a
time. The person decides. The plan becomes a GitHub issue, the change lands on `main`, and the
push is the deploy.

The person stays in charge of each decision, and the tools get enough room to do the work they
are handed at full speed. The guards keep both honest. It runs on Claude Code and Scaleway today.
The skills are plain text, the hooks and the index are Python and the stack runs in Docker, so
the parts are plain enough to move to another coding agent or cloud.

<a href="https://babon-innovations-b-v.github.io/babon-harness/diagrams/stack/loop.html">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/images/loop-dark.png">
    <img alt="The conversation loop: a task starts as one messy prompt, is read against the repository, decided, written down as an issue, built, tested, shipped and watched" src="docs/diagrams/images/loop-light.png">
  </picture>
</a>

*The loop. The picture opens the interactive page, where the arrow keys walk it step by step and
a box opens what it is and the bible section behind it.*

Published as is, with no support promised ([Support](#support)).

## What you get

| Part | What it does for you | Where it lives |
|---|---|---|
| Workflow skills | Take a request from plan to issue to build to close. | `.claude/skills/`, run as `/<name>` |
| Guards | Stop torn commits, tests that cannot fail, force pushes, stray markdown files and long waits before they land. | `.claude/hooks/` |
| Code index | Answer "where is this defined" and "who calls this" without opening or grepping files. | `.claude/index/`, the `index` server in `.mcp.json` |
| Diagrams | Draw a module as an interactive page whose boxes are each explained by a sentence in the bible. | `docs/diagrams/` |
| Shared-harness sync | Keep the harness files identical across repositories while each keeps its own hooks, glossary and bible. | `/update`, `.claude/hooks/local/` |
| The stack (optional) | Run a small company on one server: website, single sign-on, meeting minutes, a Signal assistant that keeps the agenda and makes video-call links, video calls recorded into minutes, monitoring, and deploys that test each commit. | `apps/`, `infra/`, `docker-compose.yml` |

A task usually passes through these skills:

- `grill` reads the glossary, the bible, the area rules and past issues, then asks about the plan one question at a time.
- `to-prd` writes the agreed plan as a GitHub issue and splits off sub-issues that can be picked up alone.
- `close` ships the work, records where the issue stands, and closes it only when the work is done.
- `brain-dump` sorts a page of thinking into claims, questions, decisions and issues.
- `wayfinder` turns an effort too unclear for one session into investigation issues.
- `diagnose` debugs reproduce-first; `tdd` writes tests red, then green.
- `ralph` works through the issues marked ready for an agent, unattended.
- `onboard` builds the whole stack from a fresh laptop; `update` takes in upstream changes.

The rest (audits, triage, handoff, prototype, diagrams and more) say what they do in the first
lines of their `SKILL.md`.

Among the guards, `md_guard` asks for a yes before a new markdown file exists. `issue_guard`
refuses an issue with no assignee, and force pushes and other destructive git. `commit_guard` and
the `pre-commit` hook stop torn commits and commits whose tests and register rows disagree.
`wait_guard` stops foreground waits and `output_cap` keeps long output out of the context.
`bible_guard` caps a bible chapter at 900 words and `overlay_guard` caps a per-directory
`CLAUDE.md` at 500.

The code index is [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), pinned
and checksummed, installed on first use, and reindexed after each commit.

## Requirements and costs

The harness alone needs Linux or macOS (Windows through WSL2), `git`, `curl`, `python3` 3.12 or
later, [`uv`](https://docs.astral.sh/uv/), the GitHub CLI, Claude Code on a Claude subscription,
and a GitHub account, since the backlog lives in GitHub issues and a GitHub Projects board.

The stack also needs a Scaleway account paid by a normal bank card (prepaid and most virtual cards
are refused), a domain whose DNS you control, and an Anthropic API key for the assistant and the
minutes writer, billed apart from the subscription. The assistant needs a Signal number. `node` is
needed only to draw diagrams.

Rough monthly cost, as a shape and not a quote; check Scaleway's current prices.

| Item | When | Roughly |
|---|---|---|
| One server (DEV1-M class) and its IP | always | 15 to 25 euro a month |
| Secret Manager, one secret | always | cents |
| Object storage for meeting audio | always, grows | usage-based |
| GPU node | only while transcribing | depends on the card the picker finds |
| Media box (PRO2-XS class) | only with recorded video calls | a second server, all month |
| Anthropic API | per message and per meeting | usage-based |
| Domain | yearly | about 10 euro |

Deleting the server does not stop the bill. The bucket, the secret, a registry namespace, a GPU
cluster and the media box keep billing until they are deleted too, so set a budget alert in the
Scaleway console.

## Quick start

```bash
git clone https://github.com/Babon-Innovations-b-v/babon-harness.git my-company
cd my-company
claude --dangerously-skip-permissions
```

Read [Permissions](#permissions-and-blast-radius) before using that flag.

For the whole stack, say `set up my harness` inside Claude Code. The `onboard` skill walks
thirteen phases ([`.claude/skills/onboard/phases.md`](.claude/skills/onboard/phases.md)), from a
private copy of this repository on GitHub and the board, through the Scaleway server, DNS, the
vault, Nextcloud with two-factor login, notulen and the assistant, to the GPU tier and the media
box. It takes about an hour of the agent's work and twenty minutes of yours, and it stops for the
steps only a person can take: logging in, the Scaleway key and card, the domain, the QR codes. A
broken run resumes where it stopped, because each phase first checks whether it is done.

For the harness only:

```bash
bash .claude/scripts/bootstrap.sh                  # git hooks, memory link, index binary, gh check
python3 .claude/scripts/setup-github.py --board    # labels, board, and .claude/project.json
```

Then open Claude Code and describe the first piece of work; `grill` picks it up. A component you
do not want is a folder, a line in the root `docker-compose.yml`, and possibly a workspace member
in `pyproject.toml`; delete those.

## Configuration

Nothing is read from anywhere but these three places.

| Where | Holds | Committed |
|---|---|---|
| `.claude/project.json` | repository, owner, board, people, areas | yes, filled by `setup-github.py` |
| `config/harness.env` | settings that are not secret: domain, region, names, switches | no; copy from `config/harness.env.example` |
| the vault | the full environment including every secret, one Scaleway Secret Manager secret | no; keys listed in `config/vault.env.example` |

`infra/secrets/push-env.sh <file>` pushes the vault. The server pulls it into
`$HARNESS_ROOT/harness.env` each deploy cycle, so a change is live a few minutes later.

## Components

<a href="https://babon-innovations-b-v.github.io/babon-harness/diagrams/stack.html">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/images/stack-dark.png">
    <img alt="The stack: people reach one server through Caddy or over Signal; behind it run Nextcloud with Talk, notulen, the assistant and Prometheus; the assistant books meetings on the calendar and makes Talk call links; calls run through the media box and a recorded call becomes minutes committed to GitHub; a push from the laptop reaches the deploy loop; object storage, the vault and an optional GPU tier are rented beside it" src="docs/diagrams/images/stack-light.png">
  </picture>
</a>

*The stack. The picture opens the interactive page; its laptop box opens the loop.*

### Platform

Caddy is the only public container. Accounts live in Nextcloud, and oauth2-proxy logs each private
subdomain in through it, so one login with a second factor opens everything. The dashboards are
built on the shared library `lib/dashkit`. `onboard` does the setup below; by hand it is:

1. Fill in `config/harness.env`, then assemble the vault file following `config/vault.env.example`.
2. Push it with `infra/secrets/push-env.sh`.
3. Point DNS for the domain and its `cloud`, `auth`, `notulen` and `deploy` subdomains at the server.
4. Run `docker compose --env-file $HARNESS_ROOT/harness.env up -d`.
5. Run `infra/nextcloud/oidc-setup.sh` on the server, put the two keys it writes into the vault,
   and push again.
6. Enrol a second factor for each account, then set `NEXTCLOUD_2FA_ENFORCE=1`.

### Deploy

A timer on the server and the GitHub push webhook both run `infra/auto-deploy/auto-deploy.sh`. It
takes one commit per cycle, tests it in its own tree, rebuilds only the services that changed and
checks they boot. A red or amber verdict ships nothing. The commit's GitHub page shows `vm/gate`,
`vm/build`, `vm/boot` and `vm/deploy`.

- First-time setup: `sudo HARNESS_ROOT=/opt/harness /opt/harness/repo/infra/auto-deploy/install.sh`,
  then register the GitHub webhook with the `gh api` command the script prints, pointing at
  `https://deploy.$DOMAIN/hooks/deploy`. Keep port 9000 closed in the firewall.
- `DEPLOY_STATUS_TOKEN` needs commit statuses and deployments write.
- A test needs a row in the register: `python3 -m tools.test_register --new <module> --says "<invariant>"`.
- The eject ships off. `EJECT_ENABLED=1` in `config/harness.env` (and so in the vault) arms it,
  with contents and pull-request write added to `DEPLOY_STATUS_TOKEN`; `EJECT_DRY_RUN=1` tries it
  first.
- `AUTO_DEPLOY_ENABLED=0` in `config/harness.env` and the vault pauses deploys; `systemctl disable`
  is undone within two minutes.
- The gate narrows to the tests a change can reach only after the first green nightly audit
  (`harness-gate-audit.timer`).

### Observability

A page goes out when a target or endpoint is down, a disk is almost full, memory runs short, a
container keeps restarting, a `harness-*` unit fails, the deploy loop stops, a certificate nears
expiry, the assistant or its gateway is down, or the alerting pipeline itself goes quiet. Pages
reach `SIGNAL_RECIPIENT` through the assistant while it is up and straight over Signal while it is
down. Prometheus listens on loopback only: `ssh -L 9090:127.0.0.1:9090 <server>`.

### Assistant

Upstream [OpenClaw](https://github.com/openclaw/openclaw), unmodified, holds the Signal
conversation. The tool door in `apps/assistant` triages alerts, decides what reaches a phone, and
hands the gateway its tools: calendars, the board, Prometheus, deploy status and the repository's
documents. It ships empty, with no people and no memory.

Over CalDAV against Nextcloud it reads the calendars in `AGENDA_CALENDARS`. Three switches, all
off until turned on, let it book a meeting on each attendee's calendar
(`ASSISTANT_AGENDA_WRITE=1`), put a Nextcloud Talk call link in a video meeting's location
(`ASSISTANT_VIDEO_CALL=1`), and send attendees that link on Signal shortly before the start
(`ASSISTANT_MEETING_REMINDERS=1`).

It needs `SIGNAL_*`, `ANTHROPIC_API_KEY`, `OPENCLAW_WEBHOOK_SECRET`, `OPENCLAW_GATEWAY_TOKEN` and
`AGENDA_*` in the vault. Link the bot number with signal-cli in native mode once, then run
`docker compose up -d` and `apps/assistant/workspace/apply.sh`; the deploy loop reruns `apply.sh`
after each deploy.

### Meeting minutes (notulen)

A recording made on the phone at `notulen.$DOMAIN` becomes minutes in `NOTULEN_TARGET_REPO`,
under `NOTULEN_TARGET_PATH` (default `business/minutes`). Transcription runs on the CPU by
default, where an hour of audio takes hours. The optional GPU tier takes four steps in
[`infra/gpu/CLAUDE.md`](infra/gpu/CLAUDE.md); it costs GPU node hours and opens Postgres to the
internet with only the database password in the way.

### Video calls and recording (optional)

Calls run on Nextcloud Talk, carried by an optional media box: a second server built from
[`infra/media/`](infra/media/CLAUDE.md) with a signaling server, the Janus media server and the
Talk recording server. Each call room the assistant makes has a recording bot in it. When the call
starts notulen asks Talk to record, and when it ends notulen fetches the recording from the room
owner's files and writes minutes, as for a browser recording. The room is told when recording
starts; telling people beforehand is up to the organiser.

`infra/media/deploy.sh <ip>` is the only way a change reaches the media box, which sits outside
auto-deploy, and the recorder is built from a pinned upstream commit. Turning it on is four steps
in [`infra/media/CLAUDE.md`](infra/media/CLAUDE.md), or phase 11 of `onboard`. There is no TURN
relay, so someone on a network that blocks direct UDP cannot join.

### Documents, website and design

- `uv run python -m documents invoice --sample --out out.pdf` renders a sample invoice.
  WeasyPrint needs `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1` on Debian or
  Ubuntu, `brew install pango` on macOS.
- Edit `apps/website/index.html` and push; the site follows `design/`.
- `design/tokens.css` styles the website, the documents and the dashboards together.
- Email needs a domain verified in Scaleway Transactional Email, plus `TEM_PROJECT_ID` and
  `TEM_FROM` in `config/harness.env`. Nothing is sent without an explicit yes.

### Diagrams

The two pages above, `docs/diagrams/stack.html` and `docs/diagrams/stack/loop.html`, are drawn
from the specs in `docs/diagrams/specs/` with `python3 docs/diagrams/tools/build_free.py stack
stack/loop` and served by GitHub Pages from `docs/`. They were delivered with
`BIBLE_BASE_URL=https://github.com/Babon-Innovations-b-v/babon-harness/blob/main/docs`, so a box's
bible link opens the section on GitHub; set your own address before re-delivering them.

The README pictures in `docs/diagrams/images/` are narrower layouts of the same pages
(`docs/diagrams/specs/readme/`), rendered dark and light by
`python3 docs/diagrams/tools/readme_images.py stack stack/loop`, which also needs the Python
`playwright` package.

`python3 docs/diagrams/tools/linkmap.py` checks the set. The `diagram` MCP server (in `.mcp.json`)
draws through `draw_module`, `link_module` and `check_diagrams`, with `node` for the archify
renderer. `BIBLE_BASE_URL` and `DIAGRAM_AUTHORS` are set in `config/harness.env`.

## One harness across several repositories

The shared harness is `.claude/settings.json`, `.claude/soul.md`, the skills, the index and the
hooks beside the settings. Those files stay as they came. A repository's own hooks go in
`.claude/hooks/local/`, listed in `local/hooks.json` and run by `.claude/hooks/dispatch.py`. A
change to a shared file is made once, in the repository treated as the source, and copied to the
others, while each keeps its local hooks, its `project.json`, its glossary and its bible.

For a copy of this repository, the source is this repository. `/update` fetches it as the
`upstream` remote and merges, keeping your website, design, business folder, memory, glossary and
any file you created, and taking upstream's machinery. The authors keep their own repositories in
step with a lock file that pins each shared file by hash and refuses hand edits; that script is
not in this repository.

## Without a Claude subscription

The server keeps running, since the stack, the deploy loop, monitoring and the gate never call
Claude Code. The assistant and the minutes writer keep working on the separately billed Anthropic
API key.

The loop, the skills, the hooks, setup, `/update`, `/troubleshoot` and adding a page all stop.
They exist only as prose an agent reads, and no script replaces them.

## Permissions and blast radius

The workflow assumes an unattended agent, which means `claude --dangerously-skip-permissions`. That
hands the agent your shell with your rights. During setup it holds an account-wide Scaleway key and
can create and delete servers, buckets and clusters and run up a bill. It holds GitHub
credentials, and a push to `main` is a deploy.

The hooks block a handful of shapes (force pushes, `git reset --hard`, new markdown files, torn
commits). They are not a sandbox, and nothing stops `rm -rf` or a Scaleway delete. With the flag
on, you are the review step. The alternatives are running without the flag and answering the
prompts, or running the agent in a container or virtual machine you are willing to lose. WSL2 is
not a boundary, since your Windows drives are writable from inside it.

## Support

None is promised. This is the setup one company uses, published so others can take it apart.
Issues are welcome and may be answered. Report a security problem privately through the
repository's Security tab, not in an issue.

## Credits

Babon Innovations B.V. built this setup for its own work and publishes it here with the company
taken out. The harness stands on other people's work. Licences and required texts are in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

| Work | Licence | Used for |
|---|---|---|
| [Matt Pocock's skills](https://github.com/mattpocock/skills) | MIT | `grill` and its glossary format, `triage`, `diagnose`, `tdd`, `prototype`, `improve-codebase-architecture`, `codebase-design`, `write-a-skill`, `zoom-out`, `retro`, and parts of `handoff` and `wayfinder` |
| [caveman](https://github.com/JuliusBrussee/caveman) by Julius Brussee, via Matt Pocock's skills | MIT | the `caveman` skill |
| [ponytail](https://github.com/DietrichGebert/ponytail) | MIT | the lean-code rules in `CLAUDE.md`, paraphrased |
| [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | MIT | the code index, downloaded as a pinned binary |
| [archify](https://github.com/tt-a1i/archify) v2.13.0, based on [architecture-diagram-generator](https://github.com/Cocoon-AI/architecture-diagram-generator) | MIT | the diagram renderer, vendored and modified |
| [OpenClaw](https://github.com/openclaw/openclaw) | MIT | the assistant's gateway, run unmodified |
| [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) and [signal-cli](https://github.com/AsamK/signal-cli) | MIT and GPL-3.0 | the Signal transport |
| [speaches](https://github.com/speaches-ai/speaches), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [pyannote.audio](https://github.com/pyannote/pyannote-audio) | MIT | transcription and speaker labels |
| Caddy, Nextcloud, Nextcloud Talk, oauth2-proxy, PostgreSQL, Prometheus, Alertmanager | see the notices | the stack |
| nextcloud-spreed-signaling, nextcloud-talk-recording, Janus, NATS | AGPL-3.0, AGPL-3.0, GPL-3.0, Apache-2.0 | the optional media box |

Claude Code is Anthropic's proprietary software and is not part of this repository. This project
is not affiliated with or endorsed by Anthropic.

## Licence

MIT, Copyright (c) 2026 Babon Innovations B.V. See [`LICENSE`](LICENSE).

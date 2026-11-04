---
name: onboard
description: Take a fresh laptop to a fully running harness, autonomously. Installs the remaining tools, creates the Scaleway server, deploys the stack, sets up Nextcloud with 2FA as the single sign-on, Notulen, the assistant on the owner's own Signal number and calendar, and the GPU transcription tier, and records the result in memory. Use when config/harness.env is missing, when the user says "set up my harness" or anything like it, or when setup looks only partly done (some harness.env fields empty, server missing, or a URL not responding). Resumes from wherever the previous run stopped.
---

# Onboard

Take a fresh checkout of this repository to a running harness: one Scaleway VM running the compose stack (website, Nextcloud as file cloud and single sign-on, Notulen, the assistant, observability, auto-deploy), with the accounts, DNS, vault, object storage and the optional GPU transcription tier around it.

The reader is an engineer who has never seen this repository. Assume they can read a command and repair a shell; assume they know nothing about its layout, its vault, or its deploy loop. They have installed the prerequisites below and cloned the repo. Everything after that is yours, including connecting them to GitHub and giving them their own private copy. You run with permissions skipped, so act, do not ask for permission to run commands.

Their time is the scarce thing, not yours. The setup is about an hour of your work and about twenty minutes of theirs, spread over the moments listed under "What the setup asks of the user". Everything else you decide.

## Where configuration lives

Three places, nothing else is read:

1. `.claude/project.json`, the GitHub side (repo, board, people), filled by `.claude/scripts/setup-github.py`.
2. `config/harness.env`, non-secret settings, made from `config/harness.env.example` and git-ignored. Every key there is documented in the example.
3. The vault: one Scaleway Secret Manager secret (`VAULT_SECRET_NAME`, default `harness-env`) holding the full environment, settings included. `config/vault.env.example` documents it key by key. The server pulls it each deploy cycle to `$HARNESS_ROOT/harness.env` (default `/opt/harness/harness.env`, mode 600).

Scaleway API keys come from the laptop's `scw` CLI config, never from a file in the repo. Kubernetes workers get credentials only through a Secret this skill creates, never inline.

## Prerequisites, installed by the reader before this skill runs

This skill installs the rest of the toolchain without sudo, but it cannot install these: the session has no terminal for a password prompt. Phase 1 checks them and stops with the exact command when one is missing.

- **git, curl, python3.** Debian or Ubuntu: `sudo apt-get update && sudo apt-get install -y git curl`. macOS: `xcode-select --install`.
- **uv** and **Claude Code**, both of which install into the home directory and need no sudo.
- **Optional, only for documents and invoices.** weasyprint needs pango, harfbuzz and fontconfig. Debian or Ubuntu: `sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1`. macOS: `brew install pango`. Skipping this leaves everything but documents working.

## Voice

The register is `.claude/soul.md`. During setup, what matters:

- One line before each phase: what you are about to do, and what it costs when it costs anything.
- One sentence when a phase finishes. Silence in between unless you need their hands.
- Questions are one short line plus exactly what to do or paste.
- No em dashes. Short sentences.

## What the setup asks of the user

Say this up front: it is not a hands-off install. Ten asks, plus the moments that need their hands. If you are tempted to ask anything outside this list, decide instead: passwords, server type, region, bucket names, client ids, cookie secrets are all yours to generate.

1. **The GitHub login moment** (phase 1): a short code typed in the browser.
2. **"Do you own a domain name?"** (phase 3). The harness needs one for single sign-on and certificates; if they have none, offer to register one at Scaleway (name plus the registrant contact every registrar records).
3. **The Scaleway API key** (phase 2), plus a payment card or SEPA mandate on the account.
4. **The Anthropic API key** (phase 8). Notulen minutes and the assistant both need it; skippable, but the assistant stays dark without it.
5. **Names for the Nextcloud accounts** (phase 7), one per person.
6. **The 2FA enrolment moment** (phase 7): scanning a QR code per account plus admin.
7. **A GitHub token for Notulen** (phase 8): fine-grained, contents write on the minutes repository only. Skippable; minutes then stay in the database.
8. **The assistant's Signal number** (phase 9): a number of its own (a spare SIM or a VoIP number that can receive an SMS or a call), or linking it as a second device of a phone they already use for this. Skippable.
9. **The calendar** (phase 9): which Nextcloud account the assistant reads the agenda as, and an app password created in that account. Skippable.
10. **A GitHub token for the assistant** (phase 9): read access to the repository, plus issues write only if they want it to file issues. Skippable.

The moments that need their hands:

- **DNS records at an outside registrar** (phase 5), only when the domain is registered somewhere other than Scaleway.
- **Scanning the 2FA QR codes and saving the backup codes** (phase 7).
- **Saving the Nextcloud temporary passwords** (phase 7).
- **Scanning a Signal link code or typing an SMS code** (phase 9), when the assistant gets a number.
- **Recording a short test meeting** (phase 8, and once more in phase 10 when the GPU tier lands).

## How to run it

Work through the phases in [phases.md](phases.md). Each phase is idempotent and starts with a detection check; if the check says the phase is already done, say so in half a sentence and move on. That is also how you resume a half-finished setup. Never track progress with a step counter.

## Orchestration: front-load the human, then build in parallel

1. **The human block, phases 0 to 4 in order.** GitHub login, the domain question, the Scaleway key and card. While asking for the Scaleway key, mention the errands they can run meanwhile: the Anthropic key (console.anthropic.com) and, if they want the assistant on Signal, a number for it. After phase 4 the vault is filled and the server exists; tell them the next twenty minutes are yours.
2. **The parallel block, zero user input.** Spread independent work over general-purpose subagents and run them CONCURRENTLY:
   - worker A: phase 4a steps 1 to 5 without the vault write (the cluster, its pools and their fallbacks, the secret store's key), then phase 10 step 1 (registry, worker image build). It writes nothing to the vault; it returns the cluster id, the project id, the secret store's key halves and the image reference.
   - worker B: phases 5 and 6 end to end (DNS, provisioning, scoped key, deploy, auto-deploy). It is the only vault writer in this block.
   - worker C: phase 8 step 1 only, the bucket. It returns bucket name, endpoint and region.
   If a worker fails twice, apply that phase's own fallback and keep the rest moving.

   **One vault writer at a time.** The vault update is an unlocked read-modify-write on one secret, so two writers silently lose one set of values. During this block the writer is worker B; A and C return values, and you fold them into one new version in the closing block.
3. **The closing human block.** Interrupt them once, with everything that needs their hands in one sitting: Nextcloud accounts, QR codes and the single sign-on (phase 7), storage plus the Anthropic and Notulen keys in one vault version (phase 8, with the live test recording), the assistant (phase 9), the cluster's vault key (phase 4a steps 5 and 6), the GPU wiring (phase 10 steps 3 to 9), video calls if they want them (phase 11), then finish (phase 12).

| Phase | Does | Done when |
|---|---|---|
| 0 | Explain the plan | user has seen the short overview |
| 1 | Laptop tools + GitHub | `gh auth status` ok, origin is theirs AND private, project.json filled |
| 2 | Scaleway CLI | `scw account project list` returns their project |
| 3 | Settings file + the vault | config/harness.env holds the settings, the vault secret has a version |
| 4 | Create the server | instance running, SERVER_IP saved |
| 4a | The cluster | cluster and pools from config/harness.env, CLUSTER_ID saved, the vault synced into the cluster |
| 5 | DNS | every name the Caddyfile serves resolves to SERVER_IP |
| 6 | Deploy the stack | the public names respond over HTTPS, auto-deploy timer active |
| 7 | Nextcloud, 2FA, single sign-on | accounts enrolled, enforcement on, a gated subdomain logs in through Nextcloud |
| 8 | Notulen | bucket live, service healthy, test recording done or skipped |
| 9 | The assistant | Signal number registered, calendar and GitHub wired, a first message answered, or consciously skipped |
| 10 | Fast transcription | worker image pushed, GPU cluster live, one recording through a Job (or CPU fallback recorded) |
| 11 | Video calls and recording | media node answers, Talk points at it, bot id set, or consciously skipped |
| 12 | Finish | memory note written, daily loop explained |

## Safety rules

- Never print a generated password except the one time the user must store it (the Nextcloud temporary passwords). Never repeat it later; point at where it lives instead.
- Secrets live in the vault. `config/harness.env` holds settings only, never a secret; `$HARNESS_ROOT/harness.env` is the VM's pulled cache. Never write secrets into either by hand, never print vault content, and never commit either file.
- If a phase fails twice in a row on the same error, stop. Explain in plain words what failed, what you tried, and what you would try next.
- From the end of phase 6 onward, all ssh goes through the `harness` user, never root.
- Money: the server costs roughly 15 to 25 euros per month from the moment it exists. Say this once in phase 0 and again right before creating it. The GPU tier bills only while it is processing a recording, cents per meeting; say that right before creating the cluster.

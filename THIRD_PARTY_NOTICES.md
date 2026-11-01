# Third-party notices

This repository is published under the MIT licence in [`LICENSE`](LICENSE). This file records the
third-party work it contains or needs: text adapted into it, a renderer vendored into it, and the
software it installs, pulls or downloads while it runs.

Only two things in the tree are copied from elsewhere: some skill text (section 1) and the archify
renderer (section 2). Everything in sections 3 to 7 is installed, pulled as an image or downloaded
at build time, and is never committed here. Those sections name each piece and its licence so you
know what you are running; where a licence asks something of you, it says what.

## 1. Skills adapted from other repositories

### Matt Pocock's skills

Upstream: <https://github.com/mattpocock/skills>, MIT, Copyright (c) 2026 Matt Pocock.
`codebase-design` was taken at d80fa0f4ebe0c5714af0adf8670336065233ecc6 and `retro` at a7d038f6bf7f.

These skills under `.claude/skills/` are adapted from it, wholly or in part:

| Skill | How much |
|---|---|
| `grill` (and `grill/CONTEXT-FORMAT.md`) | adapted from `grill-with-docs`; the glossary format is upstream's, nearly unchanged |
| `triage` | the state machine, role names and agent-brief format are upstream's |
| `diagnose`, `tdd`, `prototype` | adapted |
| `improve-codebase-architecture`, `codebase-design` | adapted |
| `write-a-skill`, `zoom-out`, `retro` | adapted |
| `handoff` | partly |
| `wayfinder` | a small part |

The other skills (`to-prd`, `close`, `ralph`, `tour`, `brain-dump`, the `audit-*` skills,
`my-issues`, `handoff_overseer`, `case-study`, `onboard`, `update` and the rest) were written here.

### caveman

`.claude/skills/caveman/SKILL.md` is copied unchanged from Matt Pocock's skills repository
(`skills/productivity/caveman/SKILL.md`, MIT, Copyright (c) 2026 Matt Pocock). That text is a
shortened version of `skills/caveman/SKILL.md` in <https://github.com/JuliusBrussee/caveman>, MIT,
Copyright (c) 2026 Julius Brussee. JuliusBrussee/caveman moved to Apache-2.0 at its 3.0.0 release;
the text here is from the MIT era, whose grants that project states remain valid.

The MIT permission notice both copyrights are released under, reproduced as MIT requires:

> Copyright (c) 2026 Matt Pocock
>
> Copyright (c) 2026 Julius Brussee
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

### ponytail

The lean-code rules in root `CLAUDE.md` (minimal changes, no from-scratch solutions, delete dead
code) are paraphrased from <https://github.com/DietrichGebert/ponytail>, MIT, Copyright (c) 2026
DietrichGebert. No ponytail file or verbatim text ships.

### Ideas cited by name

Some skill prose cites ideas rather than copying text: John Ousterhout's deep modules and "Design
It Twice", Michael Feathers' seams, and Geoffrey Huntley's "Ralph" loop, which the `ralph` skill is
named after. Citing an idea needs attribution, which those files carry, and no permission.

## 2. archify (vendored renderer)

`.claude/skills/archify/` is <https://github.com/tt-a1i/archify> at release v2.13.0 (commit
2c1f8ac), modified here: colour tokens in `template.html`, the renderers, the geometry, the
validators, and fewer examples. It is itself based on
<https://github.com/Cocoon-AI/architecture-diagram-generator>. Both are MIT, and the full licence
with both copyright lines ships unchanged at `.claude/skills/archify/LICENSE`:

> Copyright (c) 2026 tt-a1i (Archify)
> Copyright (c) 2025 Cocoon AI (original "architecture-diagram-generator")

archify moved to Apache-2.0 after this release; the move does not cover v2.13.0. Refreshing to
v3.x means taking on Apache-2.0 terms (its `LICENSE`, `NOTICE` and `LICENSE-MIT`, and a statement
of changes) and checking the brand marks v3.x bundles, some of which carry non-commercial
licences. `docs/diagrams/tools/build_free.py` and `deliver.sh` run this renderer through node.

## 3. Downloaded binaries

| Piece | Licence | How it arrives |
|---|---|---|
| [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) v0.12.1 | MIT, Copyright (c) 2025 DeusData | `.claude/index/install.sh` downloads the release named in `.claude/index/pin.env` and checks both checksums; the tarball carries its own `LICENSE` |
| [adnanh/webhook](https://github.com/adnanh/webhook) 2.8.1 | MIT | downloaded by `infra/auto-deploy/install.sh` |

## 4. Container images

Pulled by the compose fragments and run unmodified. A name in a compose file is a reference, not a
copy, so nothing here is redistributed by this repository.

| Image | Licence | Used by |
|---|---|---|
| [OpenClaw](https://github.com/openclaw/openclaw) `ghcr.io/openclaw/openclaw`, 2026.9.1 (ad6fe23), pinned by digest `sha256:6afe42854c87471188b9c4f8dce6bbc14005a48d8e1592846548b32508754f84` | MIT, Copyright (c) 2026 OpenClaw Foundation | the assistant's gateway |
| [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api), digest `sha256:2cf09d66a86fdd210e42ee91662216364acc27da1163a8c44167a77ea3a6559a` | MIT, Copyright (c) 2020 bbernhard | the assistant's Signal account |
| [signal-cli](https://github.com/AsamK/signal-cli), inside that image | GPL-3.0 | used over HTTP, unmodified |
| [speaches](https://github.com/speaches-ai/speaches), digest `sha256:21e3df06d842fb7802ab470dd77c25f0e8c0d22950e8d8c6ae886e851af53ef8` | MIT, Copyright (c) 2024 Fedir Zadniprovskyi | voice notes, profile `voice` |
| [Caddy](https://github.com/caddyserver/caddy) `caddy:2.11.7` | Apache-2.0 | the front door |
| [Nextcloud server](https://github.com/nextcloud/server) `nextcloud:34.0.5-apache` | AGPL-3.0 | accounts, files, single sign-on |
| [Nextcloud oidc app](https://github.com/H2CK/oidc) | AGPL-3.0 | installed into Nextcloud at runtime |
| [oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy) v7.15.5 | MIT | the single sign-on client |
| [PostgreSQL](https://www.postgresql.org) `postgres:16` | PostgreSQL License | the stack database |
| [Prometheus](https://github.com/prometheus/prometheus) `prom/prometheus:v3.4.1` | Apache-2.0 | metrics and rules |
| [Alertmanager](https://github.com/prometheus/alertmanager) `prom/alertmanager:v0.28.1` | Apache-2.0 | alert routing |
| [node_exporter](https://github.com/prometheus/node_exporter) `prom/node-exporter:v1.9.1` | Apache-2.0 | host metrics |
| [blackbox_exporter](https://github.com/prometheus/blackbox_exporter) `prom/blackbox-exporter:v0.27.0` | Apache-2.0 | HTTPS and certificate probes |
| [nginx](https://nginx.org) `nginx:alpine` | BSD-2-Clause | the website |
| [Python](https://www.python.org) `python:3.12-slim` | PSF License, on a Debian base | the assistant's door, the alert relay, notulen |
| `amazon/aws-cli` | Apache-2.0 | the assistant's Signal registration backup to S3 |
| [Nextcloud Talk](https://github.com/nextcloud/spreed) (`spreed`) | AGPL-3.0 | video calls, installed into Nextcloud by `infra/media/connect-talk.sh` |
| [nextcloud-spreed-signaling](https://github.com/strukturag/nextcloud-spreed-signaling) `strukturag/nextcloud-spreed-signaling:6046e47` | AGPL-3.0 | the media box's signaling server (optional) |
| [NATS](https://github.com/nats-io/nats-server) `nats:2.10` | Apache-2.0 | the media box's message bus (optional) |

**AGPL.** Nextcloud and its oidc app are AGPL-3.0. Running them unmodified is fine. If you patch
either and serve it to other people over a network, AGPL section 13 obliges you to offer those
people the modified source.

**Built on the media box, not pulled (optional).** `infra/media/setup.sh` clones two sources at
pinned commits and builds them on the media box: [Janus](https://github.com/meetecho/janus-gateway)
(GPL-3.0), through the Dockerfile in nextcloud-spreed-signaling, and
[nextcloud-talk-recording](https://github.com/nextcloud/nextcloud-talk-recording) (AGPL-3.0).
Nothing of either is in this repository. The recorder is modified before it is built
(`infra/media/patches/recording_pulse_sink_name.py`); the recording server is reached by your own
Nextcloud, not offered to other people, but if you serve that modified recorder to others over a
network, AGPL section 13 obliges you to offer them its source.

**Apache-2.0.** The Apache-licensed pieces above are used as published images, not copied or
modified here, so no `NOTICE` text is owed by this repository. If you build and redistribute a
modified image of one, its `NOTICE` file and a statement of your changes go with it.

## 5. The GPU worker image (optional)

`infra/gpu/Dockerfile` builds an image you push to your own registry. Nothing below is in this
repository; it is installed or downloaded during that build.

| Piece | Licence |
|---|---|
| `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime` base, PyTorch | BSD-3-Clause |
| NVIDIA CUDA runtime and cuDNN in that base | NVIDIA licence agreements |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT, Copyright (c) 2023 SYSTRAN |
| CTranslate2 | MIT |
| Whisper large-v3 and medium weights, as Systran's CTranslate2 conversions | MIT, per the model cards |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) 3.3.2 | MIT, Copyright (c) 2020 CNRS |
| pyannote/speaker-diarization-3.1 and pyannote/segmentation-3.0 | MIT, gated on Hugging Face |
| FFmpeg (Debian build) | GPL-2.0-or-later |
| huggingface-hub | Apache-2.0 |

The pyannote models are gated: whoever builds or runs the worker accepts their terms on Hugging
Face with their own account and `HF_TOKEN`. Pushing a built worker image to a **public** registry
redistributes the NVIDIA components under NVIDIA's licence and FFmpeg under the GPL, which carries
obligations of its own; a private registry, the default here, does not.

The CPU path in notulen installs faster-whisper as the optional `whisper` extra and downloads the
`medium` weights at first use.

## 6. Python dependencies

Declared in the `pyproject.toml` files and installed from PyPI by `uv sync`; none is vendored.
Most are MIT, BSD or Apache-2.0: FastAPI and Starlette (MIT), uvicorn (BSD-3-Clause), pydantic
(MIT), anthropic (MIT), mcp (MIT), kubernetes (Apache-2.0), boto3 and botocore (Apache-2.0),
requests (Apache-2.0), python-multipart (Apache-2.0), httpx (BSD-3-Clause), pytest (MIT), Jinja2
and MarkupSafe (BSD-3-Clause), WeasyPrint (BSD-3-Clause), PyYAML (MIT), pypdf (BSD-3-Clause, tests
only), caldav (Apache-2.0 or GPL-3.0, at your choice) and icalendar (BSD-2-Clause).

Not all are permissive. A scan of the installed environment on 31 October 2026 found these:

- **psycopg 3**, **psycopg2-binary** (LGPL-3.0), and **recurring-ical-events** and
  **x-wr-timezone** (LGPL-3.0-or-later, pulled in by caldav). They are used as unmodified
  libraries, which the LGPL allows without opening your own code.
- **certifi** (pulled in by requests) is MPL-2.0, which applies to its own files only.
- **pyphen** (pulled in by WeasyPrint) is offered under GPL, LGPL or MPL at your choice.
- **caldav**, **calendaring-config** and **icalendar-searcher** are GPL-3.0-or-later or
  Apache-2.0 at your choice.

Re-run a licence scan after changing dependencies.

## 7. Claude Code, and other tools you install

Claude Code is Anthropic's proprietary software. It is not open source and not redistributed here.
You install it yourself and your use of it is governed by Anthropic's terms and your Claude
subscription, not by this repository's licence. The assistant and the minutes writer also call the
Anthropic API with your own API key, which is separate billing under separate terms.

This project is not affiliated with, sponsored by, or endorsed by Anthropic. "Claude" and
"Anthropic" are Anthropic's trademarks; the MIT licence grants no trademark rights.

Docker, git, the GitHub CLI, the Scaleway CLI, uv and node are installed by you under their own
licences.

## Fonts

No font file ships. The design system uses system font stacks; the diagram pages load JetBrains
Mono (SIL Open Font License 1.1) from Google Fonts when viewed. A font file you add later brings
its own licence file with it.

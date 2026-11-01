# infra/media

The optional media box: a second server that carries Nextcloud Talk's video calls (a signaling server and the Janus media server) and records them (the Talk recording server). A recorded call becomes minutes through notulen's `/api/talk/webhook` (`apps/notulen/app/entrypoints/talk_routes.py`). Bible: `infra/media`.

```
media/
  docker-compose.yml   caddy, nats, janus, signaling, recording (host networking)
  Caddyfile            HTTPS for signaling.$DOMAIN and recording.$DOMAIN
  templates/           signaling.conf.tmpl, recording.conf.tmpl, rendered by setup.sh
  patches/             recording_pulse_sink_name.py, applied to the pinned recorder
  provision.sh         laptop: firewall, server, Docker
  deploy.sh            laptop: vault -> .env, copy, setup.sh, compose up
  setup.sh             box: clone the pinned sources, patch, render the configs
  connect-talk.sh      main server: Talk -> signaling + recording, install the bot
  snapshot.sh          laptop: back up the box, keep the newest 7
```

## Turning it on, in order

1. `provision.sh`; put the printed IP in `MEDIA_PUBLIC_IP`; DNS A records `signaling` and `recording` to it.
2. The six `TALK_*` secrets and `MEDIA_PUBLIC_IP` into the vault (`config/vault.env.example` says what each is).
3. `infra/media/deploy.sh <ip>`.
4. On the main server, `infra/media/connect-talk.sh`; put the bot id it prints in `OPENCLAW_TALK_BOT_ID`; set `ASSISTANT_VIDEO_CALL=1`.

## Rules

- **Outside auto-deploy on purpose.** A push to `main` changes nothing here; `deploy.sh` is the only way a change reaches the box. The file is `docker-compose.yml`, never `compose.yml`, or the deploy loop would start these services on the main server.
- **The recorder is built from a pinned commit, never pulled.** It touches every meeting's audio and video. Moving `SIG_COMMIT` or `REC_COMMIT` in `setup.sh` is a deliberate edit, and the signaling image tag in `docker-compose.yml` moves with `SIG_COMMIT`.
- **Never the project's default security group**: it accepts all inbound. `provision.sh` makes one that drops by default.
- **No TURN relay.** Someone on a network that blocks direct UDP cannot join a call.
- **Nothing restarts a crashed service but Docker's restart policy**, and nothing pages about this box. Back it up with `snapshot.sh`; its state is not all in the repository.
- **Recording needs the people in the call told.** The room gets a notice when recording starts; telling them beforehand is the organiser's job and nothing enforces it.
- Only the call rooms the assistant creates are recorded: the bot is enabled per room by `create_video_call`.

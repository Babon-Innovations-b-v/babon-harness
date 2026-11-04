# infra/media

What the media node runs: Nextcloud Talk's video calls (a signaling server and the Janus media server) and their recording (the Talk recording server). It runs as one pod on the one node of the `media` pool role; the manifests are in `infra/k8s/media/`, whose overlay has the cluster rules. A recorded call becomes minutes through notulen's `/api/talk/webhook` (`apps/notulen/app/entrypoints/talk_routes.py`). Bible: `infra/media`.

```
media/
  Caddyfile             HTTPS for signaling.$DOMAIN and recording.$DOMAIN
  templates/            signaling.conf.tmpl, recording.conf.tmpl (@NAME@ filled from the vault)
  Dockerfile.janus      Janus, from pinned upstream sources
  Dockerfile.recording  the recorder at a pinned commit, patched
  patches/              recording_pulse_sink_name.py, applied in the recorder build
  connect-talk.sh       main stack: Talk -> signaling + recording, install the bot
```

## Turning it on, in order

1. `POOL_ROLES` includes `media`; `infra/cluster/create-cluster.sh` made its pool. Reserve a flexible IP in the media role's first zone (`POOL_MEDIA_ZONES`), put its address in `MEDIA_PUBLIC_IP`, DNS A records `signaling` and `recording` to it.
2. Build and push both images with one new tag, never reusing one, and put it in `MEDIA_IMAGE_TAG`:
   `docker build -f infra/media/Dockerfile.janus -t $IMAGE_REGISTRY/media-janus:<tag> infra/media`, the same with `Dockerfile.recording` and `media-recording`, then `docker push` both.
3. One vault version: the six `TALK_*` secrets and `MEDIA_IP_SECRET_KEY` (`config/vault.env.example` says what each is).
4. `infra/cluster/apply.sh`. The re-attach CronJob moves the IP onto the node within a minute; the pod waits in `wait-for-media-ip` until it is there.
5. `connect-talk.sh`; put the bot id it prints in `OPENCLAW_TALK_BOT_ID`; set `ASSISTANT_VIDEO_CALL=1`. It runs `occ` through compose; against the cluster run its `occ` lines with `kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- su -s /bin/sh www-data -c 'php occ ...'`.

## Rules

- **The recorder is built from a pinned commit, never pulled.** It touches every meeting's audio and video. Moving `REC_COMMIT` or the Janus versions is a deliberate edit, and the signaling image tag in `infra/k8s/media/media-stack.yaml` moves with the commit `Dockerfile.janus` names.
- **A template placeholder is `@NAME@`, never `${NAME}`.** `apply.sh` refuses any `${...}` it has no setting for, and these values are secrets that live only in the vault.
- **The media pool's security group opens 80, 443 and UDP 20000-40000, nothing else**; `--rtp-port-range` in the Deployment must equal its UDP rule. Never the project's default security group: it accepts all inbound.
- **No TURN relay.** Someone on a network that blocks direct UDP cannot join a call.
- **Recording needs the people in the call told.** The room gets a notice when recording starts; telling them beforehand is the organiser's job and nothing enforces it.
- Only the call rooms the assistant creates are recorded: the bot is enabled per room by `create_video_call`.

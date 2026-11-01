#!/usr/bin/env bash
# setup.sh: prepare /opt/media-stack on the media box for `docker compose up`.
# Runs ON the box, from the directory deploy.sh copied this one to. Clones the
# two pinned upstream sources (Janus and the recorder are built from them),
# applies the recorder patch, and renders the config templates with ./.env.
# Idempotent.
#
# Why pinned and built here rather than pulled as a published image: the
# recorder touches every meeting's audio and video, and an upstream release
# must never walk onto this box unnoticed. Moving a pin is an edit here.
#
# FAILURE POLICY: fail-loud (`set -euo pipefail`).
set -euo pipefail

SIG_COMMIT="${SIG_COMMIT:-6046e47bffd8de5b35bf042c5aa07082ffffbd64}"   # nextcloud-spreed-signaling
REC_COMMIT="${REC_COMMIT:-c3a88fc23e045e7dfe0ea56a9aeccf71d8163a0b}"   # nextcloud-talk-recording

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
[ -f .env ] || { echo "missing ./.env; run deploy.sh from the laptop"; exit 1; }

clone_at() {
    local url="$1" dir="$2" commit="$3"
    [ -d "$dir/.git" ] || git clone "$url" "$dir"
    git -C "$dir" fetch --depth 1 origin "$commit" 2>/dev/null || git -C "$dir" fetch origin
    git -C "$dir" checkout -q "$commit"
}
clone_at https://github.com/strukturag/nextcloud-spreed-signaling.git nextcloud-spreed-signaling "$SIG_COMMIT"
clone_at https://github.com/nextcloud/nextcloud-talk-recording.git   nextcloud-talk-recording   "$REC_COMMIT"

# The recorder's PULSE_SINK must be the sink name, not its index, or a
# recording has video and silent audio. Applied after checkout, because the
# checkout would revert a hand patch; stops here if upstream moved the line.
python3 patches/recording_pulse_sink_name.py nextcloud-talk-recording/src/nextcloud/talk/recording/Service.py

command -v envsubst >/dev/null || apt-get install -y gettext-base >/dev/null
set -a; . ./.env; set +a
envsubst '${DOMAIN} ${TALK_SESSION_HASHKEY} ${TALK_SESSION_BLOCKKEY} ${TALK_SIGNALING_SECRET} ${TALK_INTERNAL_SECRET}' \
    < templates/signaling.conf.tmpl > signaling.conf
envsubst '${DOMAIN} ${TALK_RECORDING_SECRET} ${TALK_INTERNAL_SECRET}' \
    < templates/recording.conf.tmpl > recording.conf
chmod 600 .env
chmod 644 signaling.conf recording.conf
echo "setup done: sources at the pinned commits, signaling.conf and recording.conf rendered"

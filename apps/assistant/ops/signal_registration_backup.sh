#!/usr/bin/env bash
# signal_registration_backup.sh: copy the Signal registration somewhere safe.
#
# WHAT IS AT RISK. The `signal_data` volume holds the registration of the
# assistant's Signal number: its identity keys and its link to the phone.
# Lose it and the number has to be registered or linked again by hand, and
# every contact sees a safety-number change.
#
# WHAT THIS DOES. Archives the volume, while signal-cli keeps running, into
# $HARNESS_ROOT/backups/signal-cli-data-<UTC stamp>.tar.gz (mode 600, the
# newest KEEP kept), and, when the S3 settings are in the environment file,
# uploads the same archive to s3://$S3_BUCKET/backups/signal-cli-data/.
#
# RESTORE: stop signal-cli, unpack the archive into the volume
# (`docker run --rm -v <project>_signal_data:/data -v $PWD:/in alpine
# tar xzf /in/<archive> -C /data`), start signal-cli.
#
# Settings come from $HARNESS_ROOT/harness.env, the file the deploy loop pulls
# from the vault: S3_ENDPOINT, S3_REGION, S3_BUCKET, S3_ACCESS_KEY,
# S3_SECRET_KEY. Without them the copy stays on this server only and says so.
#
# FAILURE POLICY: Tier-1 fail-loud (`set -euo pipefail`). A backup that cannot
# be written must say so: the timer's OnFailure= pages.
set -euo pipefail
umask 077

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
ENV_FILE="${ENV_FILE:-$HARNESS_ROOT/harness.env}"
VOLUME="${SIGNAL_VOLUME:-harness_signal_data}"
DEST="$HARNESS_ROOT/backups"
KEEP="${KEEP:-14}"

if [[ -r "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

docker volume inspect "$VOLUME" >/dev/null 2>&1 || {
    echo "no docker volume $VOLUME; is the assistant running under that compose project?" >&2
    exit 1
}

mkdir -p "$DEST"
archive="signal-cli-data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
docker run --rm -v "$VOLUME":/data:ro alpine:3 tar czf - -C /data . > "$DEST/$archive.part"
mv "$DEST/$archive.part" "$DEST/$archive"

size=$(stat -c %s "$DEST/$archive")
if [[ "$size" -lt 1000 ]]; then
    echo "the archive is $size bytes, which is too small to be a registration" >&2
    exit 1
fi
ls -1t "$DEST"/signal-cli-data-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f

if [[ -n "${S3_BUCKET:-}" && -n "${S3_ACCESS_KEY:-}" && -n "${S3_SECRET_KEY:-}" ]]; then
    docker run --rm -v "$DEST":/backups:ro \
        -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
        -e AWS_DEFAULT_REGION="${S3_REGION:-fr-par}" \
        amazon/aws-cli s3 cp "/backups/$archive" "s3://$S3_BUCKET/backups/signal-cli-data/$archive" \
        ${S3_ENDPOINT:+--endpoint-url "$S3_ENDPOINT"} >/dev/null
    echo "signal registration backed up to $DEST/$archive and s3://$S3_BUCKET ($size bytes)"
else
    echo "signal registration backed up to $DEST/$archive ($size bytes); no S3 settings, so it is on this server only"
fi

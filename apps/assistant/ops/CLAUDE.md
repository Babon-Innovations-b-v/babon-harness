# apps/assistant/ops/

Operator scripts.

- `rotate_webhook_secret.sh start|finish <env-file>`: a zero-downtime rotation in two vault pushes, one deploy cycle apart. Never skip `finish`, or the old secret stays valid.
- `signal_registration_backup.sh`: archives the Signal registration volume to the server and, when the S3 settings exist, to the bucket. Losing that volume means linking the number again by hand.

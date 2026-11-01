# apps/notulen

The meeting-minutes dashboard (`notulen.$DOMAIN`, behind the single sign-on) and its GPU worker. The browser records in 5 s chunks, the server stitches and stores the audio in S3, whisper transcribes it (GPU worker, or this container's CPU when `GPU_ENABLED=0`), Claude writes the minutes from `inputs/notulen_template.md`, and the dashboard commits them to `NOTULEN_TARGET_REPO` under `NOTULEN_TARGET_PATH`. Bible: `apps/notulen`; the GPU side is `infra/gpu` and `infra/gpu-jobs`.

```
notulen/
  app/          FastAPI dashboard: entrypoints, gates, core (minutes, publish, sessions, board), shared, inputs (SPA)
  entrypoints/  worker.py, the GPU worker (no imports from app/)
  inputs/       notulen_template.md, used by both runtimes
  shared/       worker_constraints.txt, the GPU image pins
  tests/        the module's tests
  Dockerfile    the dashboard image (build context: repository root)
  compose.yml   the `notulen` service, included from the root compose file
```

## Twin rule

`entrypoints/worker.py` duplicates, on purpose, the transcript block grammar, the speaker paragraph of the prompt, the job-update column allowlist, the `no_speech`/`too_short` constants and floors, and the attendee cleaning from `app/`. The GPU image copies only that file and the template. Change one side, change the other; `tests/` fails when the speaker rule or the attendee parse drifts.

## Rules

- **Never a credential in a pod spec.** The worker reads every secret from the `notulen-worker-secrets` Secret by `secretKeyRef` (`infra/gpu/apply.sh` creates it). `infra/gpu-jobs` has a test for this.
- **`complete` means committed.** Never mark a job `complete` without a commit URL; the markdown waits as `committing` and `git_writer_loop` retries every 30 s with no time window. Stuck past 15 min pages the assistant, once an hour.
- **Only the correction door overwrites.** `github_writer.py` sends no sha and walks `-2`, `-3` to a free path; `rewrite_notulen.py` and `remove_notulen.py` always send the sha they read, so concurrent edits collide with a 409.
- **The path grammar is `<NOTULEN_TARGET_PATH>/<YYYY-MM>/<who>/<YYYY-MM-DD>.md`**, `<who>` being sorted lowercase first names. Changing it is a content migration of every committed file.
- **S3 before anything that can end a session.** Finalize uploads the audio first, so a rejected or failed job keeps `s3_audio_key` and can be retried.
- **A name comes from evidence in the audio, or the label stays** ("Speaker 1"). One paragraph, identical in both twins.
- **`no_speech` (under 50 words) and `too_short` (under 5 min) are outcomes, not failures.** The worker exits 0 for both.
- **Fold stray voices after diarization, never with pyannote's `max_speakers`**, which merges the real people and keeps the noise.
- **Every page goes to the assistant's door** (`shared/assistant_door.py`, `OPENCLAW_NOTIFY_URL` plus `OPENCLAW_WEBHOOK_SECRET`) inside a Tier-2 swallow. Never page from here to Signal directly.
- **Identity is the SSO headers only** (`Remote-User`, then `Remote-Email`, `shared/identity.py`). No Basic auth, no session of its own.
- **Transcription without the GPU tier needs the `whisper` extra** (`faster-whisper`), which the image installs. A checkout without it imports fine and fails a CPU job with the import error, audio kept.
- **`/api/talk/webhook` skips the login**: the `TALK_BOT_SECRET` signature is its only gate (`infra/media`).
- **The send-to-assistant claim is taken before the call** and released only when the request never arrived.

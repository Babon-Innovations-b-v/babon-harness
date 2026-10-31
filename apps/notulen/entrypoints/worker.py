"""GPU worker for the notulen pipeline.

Runs as one Kubernetes Job per recording (created by
``gpu_jobs.create_notulen_job``). Reads its job from env vars, downloads the
audio from S3, runs pyannote diarization and whisper-large-v3 transcription on
the GPU, writes the minutes with Claude, and writes the results back to
PostgreSQL.

Twin declaration: this file is a self-contained distribution unit. The worker
image copies ONLY this file plus the template (``infra/gpu/Dockerfile``), so
it deliberately duplicates, with no import path back to the dashboard:
    - the transcript block grammar of ``app/core/minutes/transcribe.py``
      (plus speaker labels, which are GPU-only),
    - the prompt of ``app/core/minutes/notulen_writer.py``,
    - the column allowlist of ``app/shared/update_job.py``,
    - the attendee cleaning of ``app/core/sessions/attendee_list.py``.
Keep them in sync by hand; the duplication is the design, not drift.

FAILURE POLICY:
    - Job-row writes (status, transcript, markdown) are Tier-1: failures
      propagate, the worker exits 1, Kubernetes records the Job failed, and
      the dashboard's dead-job watch fails the row and pages.
    - The ai-calls bookkeeping INSERT is Tier-2 best-effort: cost accounting
      must never fail a finished set of minutes (documented swallow).
    - ``complete`` is NOT set here: the worker has no commit credential, so it
      parks the markdown as ``committing`` and the dashboard's git writer loop
      commits it.

Env vars (all required unless noted). The job fields come from the Job spec;
every credential comes from the ``notulen-worker-secrets`` Secret and the
settings from the ``notulen-worker-config`` ConfigMap, never as values:
    JOB_ID             UUID of the notulen_jobs row
    AUDIO_KEY          S3 key of the uploaded audio
    TITLE              Meeting subject
    MEETING_DATE       YYYY-MM-DD
    ATTENDEES          Comma-separated attendee list (may be empty). Its
                       length is how many voices the transcript may carry.
    AGENDA             Optional agenda text (may be empty)

    DB_URL             PostgreSQL connection string
    ANTHROPIC_API_KEY  Claude API key
    HF_TOKEN           Optional: Hugging Face token for the gated pyannote
                       models. Without it the transcript has no speaker labels.
    S3_ACCESS_KEY      S3 credentials
    S3_SECRET_KEY
    S3_BUCKET          The recordings bucket
    S3_REGION          Default: fr-par
    S3_ENDPOINT        Default: https://s3.<S3_REGION>.scw.cloud
    NOTULEN_LANGUAGE   Optional whisper language code; empty auto-detects
    NOTULEN_MODEL      Optional Claude model, default claude-sonnet-4-6

Config is read at module scope as deliberate fail-fast: a missing env var
must kill the pod at import, before any GPU time is spent.
"""
from __future__ import annotations

import gc
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("notulen_worker")

#: The shortest meeting worth writing up. A shorter one keeps its recording
#: and its transcript on the row; it just gets no minutes.
SHORTEST_MEETING_SECONDS = 300
#: And a floor on what was actually said, because length alone does not catch
#: a five-minute call that holds one word. Real meetings run about 50 to 175
#: words a minute, so five minutes of the quietest one is about 250 words and
#: this floor sits five times below that.
FEWEST_WORDS = 50

#: What the row says when a call carried no speech. Declared twin of the same
#: constant in `app/core/minutes/process_job.py`; this file is deliberately
#: self-contained and imports nothing from `app/` (the twin rule in the parent
#: overlay), so the two are kept in step by hand.
NO_SPEECH = "Nobody spoke in this recording, so there is nothing to write up."
#: Same twin rule.
TOO_SHORT = (
    "This recording is shorter than five minutes, which the team set as the\n"
    "shortest meeting worth writing up. The transcript is kept."
)


# ── Attendees ───────────────────────────────────────────────────────────────

def _one_name_per_person(names: list[str]) -> list[str]:
    """The same people, each named once. Twin of `clean_attendees` in
    ``app/core/sessions/attendee_list.py``; this file imports nothing from
    ``app/``. Where two spellings of one name arrive, the capitalised one is
    kept, so the header reads "Alice" and not "alice"."""
    kept: dict[str, str] = {}
    for name in names:
        spelling = " ".join(name.split())
        if not spelling:
            continue
        person = spelling.casefold()
        if person not in kept or (spelling[:1].isupper() and not kept[person][:1].isupper()):
            kept[person] = spelling
    return list(kept.values())


def _voices_to_keep(attendees: list[str]) -> int | None:
    """How many voices the recording can really hold: one per attendee.

    ``None`` (keep whatever diarization found) below two names, because the
    list is then too thin to trust: a guest who never set a display name is
    dropped from it, so one name can still mean two people in the room.
    """
    return len(attendees) if len(attendees) >= 2 else None


# ── Config (module-scope fail-fast, see docstring) ──────────────────────────

JOB_ID = os.environ["JOB_ID"]
AUDIO_KEY = os.environ["AUDIO_KEY"]
TITLE = os.environ["TITLE"]
MEETING_DATE = os.environ["MEETING_DATE"]
ATTENDEES = _one_name_per_person(os.environ.get("ATTENDEES", "").split(","))
AGENDA = os.environ.get("AGENDA", "")

DB_URL = os.environ["DB_URL"]
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_REGION = os.environ.get("S3_REGION", "fr-par")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT") or f"https://s3.{S3_REGION}.scw.cloud"
LANGUAGE = os.environ.get("NOTULEN_LANGUAGE") or None
MODEL = os.environ.get("NOTULEN_MODEL", "claude-sonnet-4-6")

# Silence longer than this starts a new transcript block (twin of
# app/core/minutes/transcribe.py).
PAUSE_THRESHOLD_SEC = 2.0


# ── Database helpers ────────────────────────────────────────────────────────

def _db_conn():
    import psycopg
    return psycopg.connect(DB_URL)


# Only these columns may be updated by _update_job. Interpolating a dict
# key straight into the UPDATE statement is a classic SQL-injection
# footgun even when all call sites look safe. Allowlist at the DB boundary
# so an attacker-influenced key can never reach raw SQL. Twin of
# app/shared/update_job.py.
_UPDATABLE_JOB_COLUMNS = frozenset({
    "status", "error",
    "transcript_text", "duration_secs",
    "output_markdown", "completed_at",
    "s3_audio_key",
})


def _update_job(**fields) -> None:
    """Tier-1 job-row write: raises on unknown columns or DB failure."""
    if not fields:
        return
    bad = set(fields) - _UPDATABLE_JOB_COLUMNS
    if bad:
        raise ValueError(f"Refusing to update notulen_jobs: unknown columns {sorted(bad)}")
    conn = _db_conn()
    try:
        # Column names are safe (allowlisted above); values go through
        # psycopg parameter substitution.
        sets = ", ".join(f'"{column}" = %s' for column in fields)
        vals = list(fields.values())
        vals.append(JOB_ID)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE notulen_jobs SET {sets} WHERE id = %s", vals)
        conn.commit()
    finally:
        conn.close()


def _log_ai_call(input_tokens: int, output_tokens: int, cost: float, duration_ms: int, success: bool, error: str = "") -> None:
    try:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO notulen_ai_calls (run_id, purpose, model, input_tokens, output_tokens, "
                    "cost_estimate, duration_ms, success, error) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (JOB_ID, "generate_notulen", MODEL,
                     input_tokens, output_tokens, cost, duration_ms, success, error or None),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Documented Tier-2 swallow: cost bookkeeping must never fail a
        # finished notulen (see module FAILURE POLICY).
        log.exception("Failed to record ai-call bookkeeping for job %s", JOB_ID)


# ── S3 helpers ──────────────────────────────────────────────────────────────

def _s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}),
    )


def _download_audio(local_path: Path) -> None:
    log.info("Downloading %s from S3...", AUDIO_KEY)
    _s3_client().download_file(S3_BUCKET, AUDIO_KEY, str(local_path))


# ── Audio transcode ─────────────────────────────────────────────────────────

def _transcode_to_wav(src: Path, dst: Path) -> None:
    """Transcode any audio format to 16kHz mono WAV for whisper/pyannote."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(src), "-ar", "16000", "-ac", "1",
         "-f", "wav", str(dst), "-y", "-loglevel", "error"],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")


# ── Diarization ─────────────────────────────────────────────────────────────

def _diarize(wav_path: Path) -> list[tuple[float, float, str]]:
    """Run pyannote speaker diarization on GPU. Returns [(start, end, speaker), ...].

    Unconstrained on purpose; `_fold_stray_voices` corrects the count
    afterwards. See its docstring for why the constraint is the wrong knob.
    """
    hf_token = os.environ.get("HF_TOKEN") or None
    if not hf_token:
        # The pyannote models are gated on Hugging Face. Without a token the
        # transcript still comes out, just without speaker labels.
        log.info("No HF_TOKEN: skipping diarization, the transcript has no speaker labels")
        return []

    from pyannote.audio import Pipeline
    import torch

    log.info("Loading pyannote pipeline on GPU...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    # Pyannote 3.x silently returns None when the HF token is invalid or the
    # gated model terms have not been accepted, so `.to()` blows up with the
    # cryptic "'NoneType' has no attribute 'to'". Fail loud with the cause.
    if pipeline is None:
        raise RuntimeError(
            "pyannote Pipeline.from_pretrained returned None. "
            "Cause is almost always one of: (1) HF_TOKEN missing/invalid, "
            "(2) gated-model terms not accepted at "
            "huggingface.co/pyannote/{speaker-diarization-3.1, segmentation-3.0}, "
            "(3) network block. Regenerate token + re-accept terms."
        )
    pipeline.to(torch.device("cuda"))

    log.info("Running diarization...")
    started = time.time()
    output = pipeline(str(wav_path))
    diarization = getattr(output, "speaker_diarization", output)

    turns = [
        (turn.start, turn.end, speaker)
        for turn, _track, speaker in diarization.itertracks(yield_label=True)
    ]
    n_speakers = len(set(speaker for _start, _end, speaker in turns))
    log.info("Diarization done in %.1fs: %d turns, %d speakers",
             time.time() - started, len(turns), n_speakers)

    del pipeline, output, diarization
    gc.collect()
    torch.cuda.empty_cache()
    return turns


def _fold_stray_voices(
    turns: list[tuple[float, float, str]], keep: int | None
) -> list[tuple[float, float, str]]:
    """Keep the ``keep`` voices that speak most; give the rest to their neighbour.

    Diarization can hear more people than were in the room: a two-person call
    can come back as two large voices plus a few small ones holding seconds
    each. The writer then has more labels than names to map them onto, and
    guesses.

    A stray turn goes to whichever kept voice speaks nearest to it in time,
    because a stray is nearly always a moment of one of the real speakers that
    clustered on its own: a cough, an overlap, a sentence through a door.

    This is done here and NOT by handing pyannote ``max_speakers``, which is
    worse: constrained to two clusters, it can put both people in one voice
    and the noise in the other. The clustering merges by distance, and two humans in one room are closer
    to each other than to a rattling microphone.
    """
    if not keep or not turns:
        return turns
    spoken: dict[str, float] = {}
    for start, end, speaker in turns:
        spoken[speaker] = spoken.get(speaker, 0.0) + (end - start)
    if len(spoken) <= keep:
        return turns
    loudest = {
        name for name, _ in sorted(spoken.items(), key=lambda pair: -pair[1])[:keep]
    }

    previous_kept: list[int | None] = [None] * len(turns)
    last = None
    for index, (_start, _end, speaker) in enumerate(turns):
        previous_kept[index] = last
        if speaker in loudest:
            last = index
    next_kept: list[int | None] = [None] * len(turns)
    following = None
    for index in range(len(turns) - 1, -1, -1):
        next_kept[index] = following
        if turns[index][2] in loudest:
            following = index

    folded = []
    for index, (start, end, speaker) in enumerate(turns):
        if speaker in loudest:
            folded.append((start, end, speaker))
            continue
        before, after = previous_kept[index], next_kept[index]
        if before is not None and after is not None:
            nearest = before if start - turns[before][1] <= turns[after][0] - end else after
        else:
            nearest = before if before is not None else after
        folded.append((start, end, turns[nearest][2] if nearest is not None else speaker))
    return folded


# ── Transcription ───────────────────────────────────────────────────────────

def _format_ts(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"[{minutes:02d}:{secs:02d}]"


def _find_speaker(timestamp: float, turns: list[tuple[float, float, str]]) -> str:
    for start, end, speaker in turns:
        if start <= timestamp <= end:
            return speaker
    return ""


def _merge_into_blocks(segments, speaker_turns: list[tuple[float, float, str]]) -> list[str]:
    """Merge whisper segments into ``[MM:SS] [SPEAKER] text`` blocks.

    A new block starts on a pause > PAUSE_THRESHOLD_SEC or a speaker
    change (the speaker-label half is GPU-only; the pause grammar is the
    declared twin of ``app/core/minutes/transcribe.py``).
    """
    blocks: list[str] = []
    current_block: list[str] = []
    current_speaker: str = ""
    block_start: float = 0.0
    prev_end: float = 0.0

    for segment in segments:
        seg_mid = (segment.start + segment.end) / 2
        speaker = _find_speaker(seg_mid, speaker_turns) if speaker_turns else ""
        speaker_changed = bool(speaker and current_speaker and speaker != current_speaker)

        if current_block and (segment.start - prev_end > PAUSE_THRESHOLD_SEC or speaker_changed):
            prefix = _format_ts(block_start) + (f" [{current_speaker}]" if current_speaker else "")
            blocks.append(f"{prefix} {' '.join(current_block)}")
            current_block = []
            block_start = segment.start

        if not current_block:
            block_start = segment.start
            current_speaker = speaker
        if speaker:
            current_speaker = speaker

        current_block.append(segment.text.strip())
        prev_end = segment.end

    if current_block:
        prefix = _format_ts(block_start) + (f" [{current_speaker}]" if current_speaker else "")
        blocks.append(f"{prefix} {' '.join(current_block)}")

    return blocks


def _transcribe(wav_path: Path, speaker_turns: list[tuple[float, float, str]]) -> tuple[str, float]:
    """Run whisper-large-v3 on GPU; returns (block-merged transcript, duration)."""
    from faster_whisper import WhisperModel

    log.info("Loading whisper large-v3 on GPU (float16)...")
    model = WhisperModel("large-v3", compute_type="float16", device="cuda")

    log.info("Transcribing...")
    started = time.time()
    segments, info = model.transcribe(
        str(wav_path), language=LANGUAGE, beam_size=5,
        vad_filter=True, word_timestamps=True,
    )

    blocks = _merge_into_blocks(segments, speaker_turns)
    transcript = "\n\n".join(blocks)
    log.info("Transcription done in %.1fs: %d blocks, duration=%.1fs",
             time.time() - started, len(blocks), info.duration)
    return transcript, info.duration


# ── Notulen generation ──────────────────────────────────────────────────────

def _load_template() -> str:
    for candidate in (Path("/app/notulen_template.md"),):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def _generate_notulen(transcript: str) -> str:
    import anthropic

    template = _load_template()
    agenda_block = f"\nAGENDA (given beforehand by the person recording):\n{AGENDA.strip()}\n" if AGENDA.strip() else ""

    system_prompt = f"""You are a professional minute taker.

Write the minutes of the meeting from the transcript. The transcript carries
timestamps [MM:SS] and speaker labels [SPEAKER_00], [SPEAKER_01] and so on per
block. Different labels are different people.

ATTENDEES: {", ".join(ATTENDEES)}
Link a speaker label to a name only when the transcript proves it: someone is
addressed by name, introduces themselves, or a name is said back. Without that
evidence keep the label itself everywhere ("Speaker 1", "Speaker 2"), including
the "Who" column of the action items table, and put this line under
**Attendees**: The speakers cannot be identified from the audio. Never guess a
name, and do not do it halfway either: naming half of the bullets and not the
other half is the same mistake.

TEMPLATE:
{template}
{agenda_block}
FILLING RULES:
- Subject: "{TITLE}", Date: {MEETING_DATE}, Attendees: {", ".join(ATTENDEES)}
- Minutes by: "Automatic (Whisper + Claude)"
- Write in the language the meeting was held in
- "Discussed": one subsection per topic with 2-5 bullets, name speakers where possible
- "Decisions": explicit decisions only, or "No explicit decisions taken."
- "Action items": table, every concrete task separately, deadline only when named explicitly
- Leave out small talk
- Return ONLY the filled-in template"""

    client = anthropic.Anthropic()
    started = time.time()
    try:
        # No `temperature`: the current models reject it.
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": f"TRANSCRIPT:\n\n{transcript}"}],
        )
    except Exception as exc:
        _log_ai_call(0, 0, 0.0, int((time.time() - started) * 1000), False, str(exc)[:500])
        raise

    elapsed_ms = int((time.time() - started) * 1000)
    content = ""
    if response.content:
        first = response.content[0]
        content = getattr(first, "text", "") or ""
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
    _log_ai_call(input_tokens, output_tokens, round(cost, 6), elapsed_ms, True)
    log.info("Notulen generated in %.1fs (%d in / %d out tokens, $%.4f)",
             elapsed_ms / 1000, input_tokens, output_tokens, cost)
    return content


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    log.info("Notulen worker starting: job=%s audio=%s", JOB_ID, AUDIO_KEY)
    log.info("Title=%r date=%s attendees=%s", TITLE, MEETING_DATE, ATTENDEES)

    try:
        _update_job(status="transcribing")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "audio.raw"
            wav_path = tmp / "audio.wav"

            _download_audio(raw_path)
            _transcode_to_wav(raw_path, wav_path)
            raw_path.unlink(missing_ok=True)

            speaker_turns = _fold_stray_voices(
                _diarize(wav_path), _voices_to_keep(ATTENDEES)
            )
            transcript, duration = _transcribe(wav_path, speaker_turns)

        words = len(transcript.split())
        if words < FEWEST_WORDS:
            # A call nobody spoke in is a normal thing that happens: somebody
            # starts recording, waits five minutes and stops. It is not a
            # fault. Raising here would exit non-zero, fail the Job, page, and
            # mark the row failed, sending whoever opens it looking for a bug.
            log.info("Job %s: the recording holds no speech (%d words)", JOB_ID, words)
            _update_job(
                status="no_speech",
                error=NO_SPEECH,
                duration_secs=int(duration),
            )
            return 0

        if duration < SHORTEST_MEETING_SECONDS:
            # Real words, but not a meeting. The transcript stays on the row,
            # so nothing is lost; it simply gets no minutes written up.
            log.info("Job %s: %ds is shorter than a meeting", JOB_ID, int(duration))
            _update_job(
                status="too_short",
                error=TOO_SHORT,
                transcript_text=transcript,
                duration_secs=int(duration),
            )
            return 0

        _update_job(
            status="structuring",
            transcript_text=transcript,
            duration_secs=int(duration),
        )

        notulen_md = _generate_notulen(transcript)

        # `committing`, not `complete`: the markdown is in Postgres but not yet
        # in git. The dashboard's git_writer_loop commits it and flips the row
        # to `complete`. completed_at marks markdown-ready time.
        _update_job(
            status="committing",
            output_markdown=notulen_md,
            completed_at=datetime.now(timezone.utc),
        )

        log.info("Job %s transcribed, handed to git_writer_loop for commit", JOB_ID)
        return 0
    except Exception as exc:
        log.exception("Worker failed")
        try:
            _update_job(status="failed", error=str(exc)[:2000])
        except Exception:
            # Documented swallow: the failure-mark itself failed (DB down).
            # Exit 1 below is the loud signal; the dashboard's dead-job watch
            # fails the orphaned row from the Job's Failed condition.
            log.exception("Could not mark job %s failed", JOB_ID)
        return 1


if __name__ == "__main__":
    sys.exit(main())

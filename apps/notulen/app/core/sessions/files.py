"""Per-recording-session tempfile store.

Owns the on-disk layout of a recording session:
``/tmp/notulen/<job_id>/audio.webm``, append-written chunk by chunk during
recording (chunks stream to disk, so the browser never has to hold the full
blob and an iOS tab eviction loses nothing). Does NOT own the S3 upload
(``core/sessions/upload_audio.py``) or the chunk-protocol gates
(``gates/``).

FAILURE POLICY: filesystem errors propagate (Tier-1: a chunk that cannot
be written must 5xx so the browser retries); ``cleanup()`` is best-effort
(``ignore_errors=True``) because a leftover tempdir is disk debt, never
data loss.

One public callable (``session_files``); ``SessionFiles`` is its return
type and rides with it.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Root for all per-session tempdirs. Tests monkeypatch this.
RECORDING_TMP_ROOT = Path(tempfile.gettempdir()) / "notulen"


@dataclass(frozen=True)
class SessionFiles:
    """Paths of one recording session, plus create/cleanup of its tempdir."""

    root: Path
    audio_path: Path

    def create(self) -> None:
        """Create the session tempdir + empty append-target. Idempotent."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio_path.touch(exist_ok=True)

    def cleanup(self) -> None:
        """Remove the session tempdir. Best-effort, safe to call repeatedly."""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def session_files(job_id: str) -> SessionFiles:
    """The tempfile locations for one recording session."""
    root = RECORDING_TMP_ROOT / job_id
    return SessionFiles(root=root, audio_path=root / "audio.webm")

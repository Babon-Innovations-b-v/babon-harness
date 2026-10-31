"""Input gates for the notulen dashboard (``gates/`` layer).

Validate chunked-upload requests before a job row is created or audio is
written to disk. Auth is NOT here: it lives at the edge, where Caddy sends
every request through oauth2-proxy against the Nextcloud single sign-on.

Module map (one check per file):
    meeting_date.py   : parse_meeting_date: YYYY-MM-DD on /start
    chunk_size.py     : check_chunk_size: 1 byte <= chunk <= 10 MB
    chunk_seq.py      : check_chunk_seq: next/duplicate verdict, 409 on gap
    assembled_size.py : check_assembled_size: file >= 10 KB (no upper bound)
    queue_capacity.py : check_queue_capacity: concurrent-job cap (429)
"""
from __future__ import annotations

from apps.notulen.app.gates.assembled_size import check_assembled_size
from apps.notulen.app.gates.chunk_seq import check_chunk_seq
from apps.notulen.app.gates.chunk_size import check_chunk_size
from apps.notulen.app.gates.meeting_date import parse_meeting_date
from apps.notulen.app.gates.queue_capacity import check_queue_capacity

__all__ = [
    "check_assembled_size",
    "check_chunk_seq",
    "check_chunk_size",
    "check_queue_capacity",
    "parse_meeting_date",
]

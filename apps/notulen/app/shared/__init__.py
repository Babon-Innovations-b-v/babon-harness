"""Shared contracts and helpers for the notulen dashboard (``shared/`` layer).

Module map (one concern per file):
    config.py          settings read from the environment (S3, target repo, GPU tier)
    identity.py        who(request): the signed-in person from the SSO headers
    assistant_door.py  notify_assistant(subject, body): pages go to the assistant
    slug.py            the one slug grammar for filenames and paths
    s3.py              lazy boto3 S3 client
    jobs_table.py      notulen_jobs schema bootstrap (DDL, idempotent)
    update_job.py      allowlisted UPDATE on notulen_jobs (Tier-1, propagates)
"""
from __future__ import annotations

from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from apps.notulen.app.shared.s3 import get_s3
from apps.notulen.app.shared.slug import slugify
from apps.notulen.app.shared.update_job import (
    UPDATABLE_JOB_COLUMNS,
    update_job,
)

__all__ = [
    "UPDATABLE_JOB_COLUMNS",
    "ensure_jobs_table",
    "get_s3",
    "slugify",
    "update_job",
]

"""S3 client for the notulen dashboard (cached at module level).

Owns: the boto3 client wiring (endpoint, region, retry config), all read from
``S3_ENDPOINT``, ``S3_REGION``, ``S3_ACCESS_KEY`` and ``S3_SECRET_KEY``. Does
NOT own which keys are written: callers build their own keys
(``core.sessions.upload_audio``). boto3 imports lazily so the package imports
without it.

FAILURE POLICY: this module never swallows. boto3/botocore exceptions
propagate to the caller, which decides per seam (uploads are Tier-1: a lost
recording is the product).
"""
from __future__ import annotations

import os

_s3_client = None


def get_s3():
    """Lazy-initialised boto3 S3 client for the configured endpoint."""
    global _s3_client
    if _s3_client is None:
        import boto3  # noqa: PLC0415 (keep package importable without boto3)
        from botocore.config import Config  # noqa: PLC0415

        from apps.notulen.app.shared.config import S3_ENDPOINT, S3_REGION  # noqa: PLC0415

        _s3_client = boto3.client(
            "s3",
            region_name=S3_REGION,
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )
    return _s3_client

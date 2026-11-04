"""The deploy bookmark as it lives in the cluster: ConfigMap `deploy-bookmark`.

OWNS: what a bookmark value may be. The steps read and write the file
`$STATE_DIR/last-deployed-sha` as they always did; in the cluster the `sha` key
of one ConfigMap is the durable copy, read into that file at the top of every
cycle and written back by step 90. A lost state volume then costs the verdict
cache, never the bookmark.

THREE STATES, and only two of them are a bookmark:

    `sha` holds forty hex characters ... the bookmark
    `sha` is present and empty ......... no bookmark yet (a fresh install)
    `sha` is absent, or anything else .. refused: a ConfigMap nobody seeded
                                         would otherwise read as "no bookmark",
                                         and a cycle with no bookmark takes
                                         the tip of main

FAILURE POLICY: pure; a refused value raises ValueError.
"""
from __future__ import annotations

import re

_SHA = re.compile(r"[0-9a-f]{40}")


def bookmark_sha(configmap: dict) -> str:
    """The bookmark a ConfigMap document carries: a full sha, or '' for none yet."""
    data = configmap.get("data") if isinstance(configmap, dict) else None
    if not isinstance(data, dict) or "sha" not in data:
        raise ValueError("ConfigMap deploy-bookmark carries no `sha` key; it was never seeded")
    value = str(data["sha"]).strip()
    if value and not _SHA.fullmatch(value):
        raise ValueError(f"ConfigMap deploy-bookmark's `sha` is not a full commit sha: {value[:60]!r}")
    return value

"""Test defaults for the assistant package.

The tests pin a zone with a daylight-saving change, so the clock conversions
they assert are exercised across both offsets, and a project file with four
placeholder people and two areas, so the board rules have something to hold.
Production reads ASSISTANT_TIMEZONE from the owner's settings and
`.claude/project.json` from the repository; nothing here leaks into either.
"""
import json
import os
import tempfile

os.environ.setdefault("ASSISTANT_TIMEZONE", "Europe/Amsterdam")
os.environ.setdefault("ASSISTANT_NAME", "Assistant")

_PROJECT = {
    "repo": "owner/repo",
    "owner": "alex-example",
    "area_label_prefix": "area:",
    "areas": ["dev", "finance"],
    "backlog_prd": 151,
    "people": {
        "Alex": "alex-example",
        "Sam": "sam-example",
        "Robin": "robin-example",
        "Kim": "kim-example",
    },
}
if "HARNESS_PROJECT_JSON" not in os.environ:
    _handle, _path = tempfile.mkstemp(prefix="assistant-project-", suffix=".json")
    with os.fdopen(_handle, "w", encoding="utf-8") as _file:
        json.dump(_PROJECT, _file)
    os.environ["HARNESS_PROJECT_JSON"] = _path

"""`python -m apps.assistant.workspace`: print everything the gateway is
handed, as one JSON object, for `workspace/apply.sh`.

One call, because separate calls could straddle a restart and mix two renders:

    {"files": {"AGENTS.md": ..., "SOUL.md": ..., "USER.md": ..., "IDENTITY.md": ...},
     "config_patch": {...}, "automations": {...}}

It runs inside the assistant container, which holds the principles and the
person rules in its state database and the settings in its environment.

FAILURE POLICY: Tier-1 fail-loud. A render that cannot complete exits non-zero
with the reason on stderr, and the caller writes nothing.
"""
from __future__ import annotations

import json
import sys

from apps.assistant.workspace import render_workspace
from apps.assistant.workspace.fragment import render_automations, render_config_patch


def main() -> int:
    payload = {
        "files": {item.name: item.text for item in render_workspace()},
        "config_patch": render_config_patch(),
        "automations": render_automations(),
    }
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())

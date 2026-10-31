"""Declare the assistant's scheduled reports on the OpenClaw gateway.

Reads `gateway_automations.json` beside this file and issues one
`openclaw cron add --declaration-key <key>` per entry. Upstream treats the
declaration key as the job's identity, so re-declaring an unchanged job is a
no-op and a changed one is updated in place: this can run on every deploy.

WHY A SCRIPT AND NOT A CONFIG FRAGMENT. Everything else the gateway needs is
applied as JSON through `openclaw config patch` (`gateway_config_patch.json`),
which is how the workspace, the tool door and the transcription route are
wired. Automations are the exception: the gateway keeps jobs in its own store
and `openclaw.json` has a `cron` key holding switches only, so there is no
fragment that can carry a job. The CLI is the only door.

THE GATEWAY NO LONGER DELIVERS EITHER REPORT. `--no-deliver`
sets `delivery.mode` to `none`, and the ask tells the assistant to send the report with
`message_teammate`, the tool in our own door. Upstream's `--announce` posted the
model's final text straight to the phone, so the only lever on a report's length
was a sentence in the ask, and a sentence like "three sentences" does not
bound length. On this road
the report crosses `core/tools/team/message_teammate.py`, where the limit is
`MAX_MESSAGE_WORDS` and refusing is arithmetic.

Naming a delivery channel is also what REMOVES the messaging tools from the run
(upstream: "set channel/to for a specific chat, no messaging tool inside the
run"), so `--announce` and this road cannot both be had. The recipient is no
longer read here at all: `message_teammate` resolves a person against the people
registry, which is the same registry that decides the assistant may message them.

A report the model forgets to send is silence, where the old road would have
posted something. That is the trade, taken deliberately: `_too_long_refusal`
returns a string the model acts on rather than an exception, so a long report
becomes a short one instead of nothing, and a run that sent no message at all
leaves no `team_message` row in `assistant_actions`, which is a thing to look at
when a brief does not arrive.

Prints one line per automation and exits non-zero if any declaration failed,
so the caller can page rather than assume.

Single public callable: `apply_automations()`.

FAILURE POLICY: fail-loud, no swallow. A missing file, unreadable config or a
refused declaration raises or exits non-zero. The caller (`workspace/apply.sh`) is
Tier-2 and decides what a failure means for the deploy; this module's job is
to be honest about what it did.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DECLARATIONS = _HERE / "gateway_automations.json"

#: How long one `cron add` may take. The call only writes a job row; anything
#: near this means the gateway is not answering, which is worth failing on.
_TIMEOUT_SECONDS = 60


def _declare(automation: dict) -> bool:
    """Run one `cron add`. True when the gateway accepted it."""
    command = [
        "openclaw", "cron", "add",
        "--declaration-key", automation["declarationKey"],
        "--name", automation["name"],
        "--display-name", automation["displayName"],
        "--description", automation["description"],
        "--cron", automation["cron"],
        "--tz", automation["tz"],
        "--message", automation["message"],
        "--session", "isolated",
        "--agent", "main",
        # The run sends its own report through `message_teammate`; see the
        # module docstring for why the gateway must not deliver it instead.
        "--no-deliver",
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
    )
    if completed.returncode != 0:
        print(
            f"[automations] FAILED {automation['declarationKey']}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
        return False
    print(f"[automations] declared {automation['declarationKey']} ({automation['cron']})")
    return True


def apply_automations() -> int:
    """Declare every automation in the file. Returns a process exit code."""
    declarations = json.loads(_DECLARATIONS.read_text(encoding="utf-8"))["automations"]
    failed = [a for a in declarations if not _declare(a)]
    if failed:
        print(f"[automations] {len(failed)} of {len(declarations)} not declared")
        return 1
    print(f"[automations] {len(declarations)} declared")
    return 0


if __name__ == "__main__":
    sys.exit(apply_automations())

"""The media public IP goes onto the one Ready node of the media role, and only when it is not there yet.

WHAT IT PINS. `infra/k8s/media/ip-reattach.sh`, run whole as the
media-ip-reattach CronJob runs it, with `kubectl` and `curl` replaced by stubs
on PATH. The seam is those two commands: which nodes `kubectl` reports, which
server the provider's IP record names, and whether the script asks the
provider to move the IP, and to which server.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A made-up
table of nodes (name, providerID `scaleway://instance/<zone>/<server>`, Ready
status) and the server the IP sits on before the run, each with its answer
worked out by hand from the contract in the script's header: one Ready node
in the IP's zone whose server lacks the IP gets exactly one move naming that
server, also beside a NotReady node (a dead node's object lingering beside its
replacement) and when the IP is detached; the same node already holding it
gets none. Zero Ready nodes, two Ready nodes, a node in another zone and a
providerID with no server each exit non-zero and move nothing, and a move the
provider accepts but does not carry out exits non-zero.

ONE FUNCTION. Every case is a row of `CASES`.

WHAT IT WAS PROVED AGAINST. The node-count guard loosened from "exactly one"
to "at least one", so two Ready nodes reach the move and that case sees a move
it says never happens.

GUARDS. The media node port, 2026-11-04.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "ip-reattach.sh"
_IP = "203.0.113.7"
_ZONE = "zone-a"
_NODE = "11111111-1111-1111-1111-111111111111"
_OTHER = "22222222-2222-2222-2222-222222222222"

_KUBECTL = """#!/bin/bash
printf '%s' "$STUB_NODES"
"""

# A GET answers from the state file. A PATCH records its body and, unless
# STUB_STICK=0, moves the IP in the state file, as the provider does.
_CURL = """#!/bin/bash
method=GET; body=""
while [ $# -gt 0 ]; do
    case "$1" in
        -X) method=$2; shift ;;
        -d) body=$2; shift ;;
    esac
    shift
done
if [ "$method" = PATCH ]; then
    printf '%s\\n' "$body" >> "$STUB_CALLS"
    if [ "${STUB_STICK:-1}" = 1 ]; then
        python3 -c 'import json,sys;print(json.loads(sys.argv[1])["server"],end="")' "$body" > "$STUB_STATE"
    fi
    echo '{}'
    exit 0
fi
python3 -c 'import json,sys;s=open(sys.argv[1]).read().strip();print(json.dumps({"ip":{"address":"x","server":({"id":s} if s else None)}}))' "$STUB_STATE"
"""


def _node(name: str, server: str, zone: str = _ZONE, ready: str = "True") -> str:
    return f"{name} scaleway://instance/{zone}/{server} {ready}\n"


def _move(server: str) -> str:
    return f'{{"server": "{server}"}}'


# (case, nodes kubectl reports, holder before, provider carries the move out,
#  exits 0, moves asked for, holder after)
CASES = [
    ("moves onto the one node", _node("media-a", _NODE), _OTHER, True, True, [_move(_NODE)], _NODE),
    ("stays when already there", _node("media-a", _NODE), _NODE, True, True, [], _NODE),
    ("attaches a detached IP", _node("media-a", _NODE), "", True, True, [_move(_NODE)], _NODE),
    ("follows the Ready node past a dead one",
     _node("media-a", _OTHER, ready="Unknown") + _node("media-b", _NODE), _OTHER, True, True, [_move(_NODE)], _NODE),
    ("refuses with no node", "", _OTHER, True, False, [], _OTHER),
    ("refuses with only a NotReady node", _node("media-a", _NODE, ready="False"), _OTHER, True, False, [], _OTHER),
    ("refuses two Ready nodes", _node("media-a", _NODE) + _node("media-b", _OTHER), _OTHER, True, False, [], _OTHER),
    ("refuses a node in another zone", _node("media-a", _NODE, zone="zone-b"), _OTHER, True, False, [], _OTHER),
    ("refuses a providerID with no server", "media-a scaleway://instance/zone-a/ True\n", _OTHER, True, False, [], _OTHER),
    ("fails when the move does not stick", _node("media-a", _NODE), _OTHER, False, False, [_move(_NODE)], _OTHER),
]


@pytest.mark.parametrize(
    ("case", "nodes", "holder", "sticks", "succeeds", "moves", "holder_after"),
    CASES,
    ids=[row[0] for row in CASES],
)
def test_the_media_public_ip_is_attached_only_to_the_one_ready_node_of_the_media_and_never_moved_when_it_is_already_there(
    tmp_path: Path,
    case: str,
    nodes: str,
    holder: str,
    sticks: bool,
    succeeds: bool,
    moves: list[str],
    holder_after: str,
) -> None:
    """One run of the script against one row of the table gives that row's exit, moves and holder."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("kubectl", _KUBECTL), ("curl", _CURL)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    state = tmp_path / "state"
    state.write_text(holder, encoding="utf-8")
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MEDIA_PUBLIC_IP": _IP,
        "MEDIA_NODE_LABEL": "role=media",
        "MEDIA_ZONE": _ZONE,
        "MEDIA_IP_SECRET_KEY": "not-a-key",
        "STUB_NODES": nodes,
        "STUB_STATE": str(state),
        "STUB_CALLS": str(calls),
        "STUB_STICK": "1" if sticks else "0",
    }
    done = subprocess.run(["bash", str(_SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    output = done.stdout + done.stderr
    assert (done.returncode == 0) == succeeds, f"{case}: exit {done.returncode}\n{output}"
    assert [line for line in calls.read_text(encoding="utf-8").splitlines() if line] == moves, f"{case}\n{output}"
    assert state.read_text(encoding="utf-8") == holder_after, f"{case}\n{output}"

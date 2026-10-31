"""stack_status says the VM's docker containers are outside its count.

WHAT IT PINS. `stack_status.execute`, the tool's public interface, over a real
`component_status` table with every registry component up: the answer still
says what "ALL UP" does not cover, and names where those containers' liveness
is read instead.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
registry and the collector. `monitor/registry.py` holds the components the
sweep checks and none of them is a VM docker container, while
`infra/observability/node_textfile/collect.py` watches the compose containers
(harness-*-1 and the assistant's named ones) and exports `harness_container_up`.
So an all-up answer is true of the registry only, and an answer that does not
say so can be read as covering the containers too.
"""
from __future__ import annotations

from apps.assistant.core import state
from apps.assistant.core.monitor.registry import REGISTRY
from apps.assistant.core.state.component_status import STATUS_UP
from apps.assistant.core.state.reset import reset_for_tests
from apps.assistant.core.tools.meta import stack_status


def test_an_all_up_answer_says_the_vm_containers_are_not_in_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    reset_for_tests()
    try:
        for component in REGISTRY:
            state.component_status.record_check(component.name, STATUS_UP, True, "", 0)
        answer = stack_status.execute({})
    finally:
        reset_for_tests()
    assert f"ALL UP ({len(REGISTRY)} components)" in answer
    assert "harness-*-1" in answer
    assert "harness_container_up" in answer
    assert all(not component.name.startswith("harness-") for component in REGISTRY)

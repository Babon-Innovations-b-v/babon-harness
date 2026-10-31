"""Step 80 removes a unit only when IT installed it and the repository dropped it.

WHAT IT PINS. `_install_units` in `steps/80-units.sh`: units found in
`*/<name>/systemd/` are installed, and the manifest of what was installed is
the only list removal reads, so a unit the owner installed by hand survives.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A verified tree
with one unit, a unit directory holding a hand-installed unit and a unit the
manifest says this step installed earlier, and stubs for sudo and systemctl.
What must remain follows from the rule above.

WHAT IT WAS PROVED AGAINST. Sweeping every installed `harness-*` unit the tree
lacks, which deletes the hand-installed one.

GUARDS. Step 80's orphan sweep.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_STEPS = Path(__file__).resolve().parents[1] / "steps"


def test_only_a_dropped_unit_this_step_installed_is_removed(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "infra/thing/systemd").mkdir(parents=True)
    (tree / "infra/thing/systemd/harness-thing.timer").write_text(
        "[Timer]\nOnCalendar=daily\nUnit=harness-thing.service\n", encoding="utf-8"
    )
    units = tmp_path / "units"
    units.mkdir()
    (units / "harness-by-hand.service").write_text("[Service]\n", encoding="utf-8")
    (units / "harness-dropped.service").write_text("[Service]\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "installed-units").write_text("harness-dropped.service\nharness-thing.timer\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "systemctl").chmod(0o755)
    script = "\n".join((
        "set -u",
        f'export PATH="{bin_dir}:/usr/bin:/bin"',
        f'LOG="{tmp_path}/log"',
        'log() { echo "$*" >> "$LOG"; }',
        f'. "{_STEPS}/doors.sh"',
        f'STATE_DIR="{state}"',
        f'UNIT_DIR="{units}"',
        'UNIT_SUDO=""',
        f'VERIFIED_TREE="{tree}"',
        "gate_red=0",
        f'. "{_STEPS}/80-units.sh"',
    ))
    subprocess.run(["bash", "-c", script], check=True, timeout=30, capture_output=True)
    remaining = sorted(path.name for path in units.iterdir())
    assert remaining == ["harness-by-hand.service", "harness-thing.timer"], remaining
    assert (state / "installed-units").read_text(encoding="utf-8").split() == ["harness-thing.timer"]

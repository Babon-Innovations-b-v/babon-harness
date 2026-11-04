"""The recorder patch swaps the sink index for its name once, and stops when upstream moved the line.

WHAT IT PINS. `infra/media/patches/recording_pulse_sink_name.py`, run by
`Dockerfile.recording` against the pinned Talk recorder. Upstream hands the browser the
PulseAudio sink's index, which libpulse ignores there, so a recording comes
out with video and silent audio. The patch must replace that one line, must
be a no-op on a second run (a rebuilt layer runs it again), and must exit
non-zero when the line is gone, so the build stops instead of shipping a
recorder that records silence.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
upstream line itself, `env['PULSE_SINK'] = audioSinkIndex`, written into a
scratch file: after one run it must be gone and a sink-name lookup present;
after a second run the file must be byte-identical; a file without the line
must give exit code 2 and stay untouched.

WHAT IT WAS PROVED AGAINST. Treating every file as already patched, so the
first run leaves the upstream line in place and the first assertion trips.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

PATCH = pathlib.Path(__file__).resolve().parents[1] / "patches" / "recording_pulse_sink_name.py"
UPSTREAM_LINE = "            env['PULSE_SINK'] = audioSinkIndex\n"


def _run(target: pathlib.Path) -> int:
    return subprocess.run([sys.executable, str(PATCH), str(target)],
                          capture_output=True, text=True).returncode


def test_the_recorder_patch_swaps_the_sink_index_for_its_name_once_and_stops_when_upstream_moved_the_line(tmp_path) -> None:
    """Patched once, unchanged the second time, refused without the anchor."""
    service = tmp_path / "Service.py"
    service.write_text("def start():\n" + UPSTREAM_LINE + "            run()\n")

    assert _run(service) == 0
    patched = service.read_text()
    assert UPSTREAM_LINE not in patched
    assert "env['PULSE_SINK'] = _sinkName" in patched

    assert _run(service) == 0
    assert service.read_text() == patched

    moved = tmp_path / "Moved.py"
    moved.write_text("def start():\n            run()\n")
    assert _run(moved) == 2
    assert moved.read_text() == "def start():\n            run()\n"

#!/usr/bin/env python3
"""Patch nextcloud-talk-recording so the browser's PULSE_SINK is the sink
NAME, not its index.

The upstream recorder sets `env['PULSE_SINK'] = audioSinkIndex` (the sink
INDEX). In this container's PulseAudio, libpulse does NOT honor an index there,
so firefox falls back to the default sink while ffmpeg records the (empty)
null-sink monitor: the recording has video but silent audio. Verified in the
recording container: `PULSE_SINK=<index>` captures a played tone at -91 dB
(silence), `PULSE_SINK=<name>` at -24 dB (audio). This resolves the name from
the index and uses it.

Idempotent: a second run is a no-op. Fail-loud: if the anchor line is gone
(upstream changed), exit non-zero so setup.sh stops rather than silently
shipping the silent-audio bug. `setup.sh` runs this against the pinned clone
after checkout (the checkout would otherwise revert a hand-patch)."""
import sys

_ANCHORS = (
    "            env[\"PULSE_SINK\"] = audioSinkIndex\n",
    "            env['PULSE_SINK'] = audioSinkIndex\n",
)
_REPLACEMENT = (
    "            # PULSE_SINK must be the sink NAME, not its index: in this\n"
    "            # container libpulse ignores an index and firefox falls back to\n"
    "            # the default sink, so the recorded null-sink monitor is silent\n"
    "            # (verified: index -> -91 dB, name -> -24 dB). Resolve the name.\n"
    "            with pulsectl.Pulse(\"pulse-sink-name-lookup\") as _pulseNameLookup:\n"
    "                _sinkName = next((s.name for s in _pulseNameLookup.sink_list() if s.index == int(audioSinkIndex)), audioSinkIndex)\n"
    "            env['PULSE_SINK'] = _sinkName\n"
)


def main() -> int:
    path = sys.argv[1]
    src = open(path).read()
    if "_pulseNameLookup" in src:
        print(f"already patched: {path}")
        return 0
    for anchor in _ANCHORS:
        if anchor in src:
            open(path, "w").write(src.replace(anchor, _REPLACEMENT))
            print(f"patched PULSE_SINK name fix: {path}")
            return 0
    print(f"ANCHOR NOT FOUND (upstream changed?): {path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

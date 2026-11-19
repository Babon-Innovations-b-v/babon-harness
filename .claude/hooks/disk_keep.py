#!/usr/bin/env python3
"""SessionStart hook: the local disk holds tools, the OS, capped caches and tmp files, never data.

Data, inputs, results, models and datasets live in object storage on every
machine; a local copy is a cache with a size cap or a tmp file deleted when its
job ends. Two leaks filled a disk anyway: agent jobs left their scratch behind
(``~/.claude/jobs/<job>/tmp``), and data piled up in folders nobody looked at.
This hook works on both, and never blocks a session:

- It starts a sweep in the background (itself under ``DISK_KEEP_SWEEP=1``, one at a time under a lock):
  each job folder under JOBS whose ``state.json`` says the job ended (ENDED),
  whose ``tmp/`` nothing touched for IDLE_SECONDS and in which no process works
  (its working folder, or the path on its command line) loses its ``tmp/``
  contents, all but the paths its ``tmp/KEEP`` file names (one path relative to
  ``tmp/`` a line). A job still working, or in a state it does not know, is left
  as it is. The same sweep measures the largest folders under the home (du, two
  levels, at least MEASURED_GB each) and what docker could reclaim, at most once
  an hour, into STATE.
- When the disk holding the home is over FULL_PERCENT used, it says one line:
  how full, the largest folders of the last measure, docker's reclaimable space
  and what the last sweep freed. The line informs; nothing is stopped.

FAILURE POLICY: fail-open. Anything unreadable or unexpected exits 0 with no
output. ``DISK_KEEP=0`` disarms it. ``DISK_KEEP_JOBS`` and ``DISK_KEEP_STATE``
name other folders, ``DISK_KEEP_FULL_PERCENT`` another threshold.
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
JOBS = Path(os.environ.get("DISK_KEEP_JOBS") or HOME / ".claude" / "jobs")
STATE = Path(os.environ.get("DISK_KEEP_STATE") or Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")
             / "disk-keep")
FULL_PERCENT = float(os.environ.get("DISK_KEEP_FULL_PERCENT") or 80)
ENDED = {"done", "finished", "failed", "error", "errored", "stopped", "cancelled", "canceled", "killed", "exited"}
IDLE_SECONDS = 3600
MEASURE_SECONDS = 3600
MEASURED_GB = 5
SHOWN = 6
KEEP = "KEEP"


def newest_change(folder):
    """The newest mtime of `folder` and everything under it (links not followed)."""
    newest = folder.lstat().st_mtime
    for parent, directories, files in os.walk(folder):
        for name in directories + files:
            try:
                newest = max(newest, os.lstat(os.path.join(parent, name)).st_mtime)
            except OSError:
                continue
    return newest


def worked_in(folders):
    """The folders of `folders` some process works in: its working folder inside one, or one on its command line."""
    found = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            words = (entry / "cmdline").read_bytes().decode(errors="replace")
            here = os.readlink(entry / "cwd")
        except OSError:
            continue
        for folder in folders:
            text = str(folder)
            if here == text or here.startswith(text + "/") or text in words:
                found.add(folder)
    return found


def kept_paths(scratch):
    """The paths relative to `scratch` its KEEP file names, the file itself among them."""
    keep = scratch / KEEP
    if not keep.is_file():
        return set()
    lines = keep.read_text().splitlines()
    return {KEEP} | {line.strip().strip("/") for line in lines if line.strip() and ".." not in line}


def removed(folder, keep, prefix=""):
    """Everything under `folder` but the paths in `keep` (relative, with `prefix` for this level) removed; bytes freed."""
    freed = 0
    for entry in sorted(folder.iterdir()):
        name = f"{prefix}{entry.name}"
        if name in keep:
            continue
        if entry.is_dir() and not entry.is_symlink() and any(path.startswith(name + "/") for path in keep):
            freed += removed(entry, keep, name + "/")
            continue
        freed += size_of(entry)
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
    return freed


def size_of(path):
    """Bytes under `path` (links not followed)."""
    if path.is_symlink() or not path.is_dir():
        return path.lstat().st_size
    total = 0
    for parent, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(parent, name)).st_size
            except OSError:
                continue
    return total


def ended_scratch(jobs, now):
    """The tmp/ folders of the jobs under `jobs` that ended, sat untouched IDLE_SECONDS and no process works in."""
    found = []
    for job in sorted(jobs.iterdir()) if jobs.is_dir() else []:
        scratch, state = job / "tmp", job / "state.json"
        if not scratch.is_dir() or not state.is_file():
            continue
        try:
            said = json.loads(state.read_text()).get("state")
        except (OSError, ValueError, AttributeError):
            continue
        if said in ENDED and now - newest_change(scratch) > IDLE_SECONDS:
            found.append(scratch)
    busy = worked_in(found)
    return [scratch for scratch in found if scratch not in busy]


def sweep_scratch(jobs, now):
    """Each ended job's scratch emptied but its KEEP paths; (jobs swept, bytes freed)."""
    swept, freed = 0, 0
    for scratch in ended_scratch(jobs, now):
        gone = removed(scratch, kept_paths(scratch))
        swept, freed = swept + (gone > 0), freed + gone
    return swept, freed


def largest(home):
    """[(GB, path)] of the largest folders under `home`, two levels down, each at least MEASURED_GB, biggest first."""
    done = subprocess.run(["du", "-x", "-k", "-d", "2", "-t", f"{MEASURED_GB}G", str(home)],
                          capture_output=True, text=True, timeout=1800)
    rows = []
    for line in done.stdout.splitlines():
        size, _, path = line.partition("\t")
        if size.isdigit() and path != str(home):
            rows.append((round(int(size) / 1024 ** 2, 1), path))
    return sorted(rows, reverse=True)


def reclaimable():
    """Docker's reclaimable space by type ('Images 114GB'), or '' without docker."""
    try:
        done = subprocess.run(["docker", "system", "df", "--format", "{{.Type}}\t{{.Reclaimable}}"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    rows = [line.split("\t") for line in done.stdout.splitlines() if "\t" in line] if done.returncode == 0 else []
    return ", ".join(f"{kind} {amount.split(' ')[0]}" for kind, amount in rows if not amount.startswith("0B"))


def read_state():
    try:
        return json.loads((STATE / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def write_state(state):
    STATE.mkdir(parents=True, exist_ok=True)
    part = STATE / f"state.json.{os.getpid()}"
    part.write_text(json.dumps(state))
    os.replace(part, STATE / "state.json")


def sweep(now=None):
    """The background sweep, one at a time: ended jobs' scratch, then the measure when it is MEASURE_SECONDS old."""
    now = time.time() if now is None else now
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "sweep.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        swept, freed = sweep_scratch(JOBS, now)
        state = read_state()
        state["swept"] = {"at": now, "jobs": swept, "gb": round(freed / 1e9, 1)}
        write_state(state)
        if now - state.get("measured", {}).get("at", 0) > MEASURE_SECONDS:
            state["measured"] = {"at": now, "folders": largest(HOME), "docker": reclaimable()}
            write_state(state)


def start_sweep():
    """This script's sweep started in a session of its own, its output nowhere: the session never waits on it."""
    subprocess.Popen([sys.executable, str(Path(__file__).resolve())], env={**os.environ, "DISK_KEEP_SWEEP": "1"},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def shown(path):
    return "~" + path[len(str(HOME)):] if path.startswith(str(HOME)) else path


def note(state, usage):
    """The one line for a disk over FULL_PERCENT, else ''."""
    percent = 100 * usage.used / usage.total
    if percent <= FULL_PERCENT:
        return ""
    measured = state.get("measured", {})
    folders = ", ".join(f"{shown(path)} {gb:.0f} GB" for gb, path in measured.get("folders", [])[:SHOWN])
    when = time.strftime("%H:%M", time.localtime(measured["at"])) if measured else ""
    parts = [f"DISK {percent:.0f}% full ({usage.free / 1e9:.0f} GB free of {usage.total / 1e9:.0f} GB)",
             f"largest folders (measured {when}): {folders or f'none over {MEASURED_GB} GB'}" if measured
             else "largest folders: being measured",
             f"docker reclaimable: {measured['docker']}" if measured.get("docker") else ""]
    swept = state.get("swept", {})
    if swept.get("jobs"):
        parts.append(f"last sweep emptied {swept['jobs']} ended jobs' scratch, {swept['gb']} GB")
    parts.append("data belongs in object storage: a local disk holds tools, the OS, capped caches and tmp files")
    return "; ".join(part for part in parts if part) + "."


def main():
    if os.environ.get("DISK_KEEP") == "0":
        return 0
    if os.environ.get("DISK_KEEP_SWEEP") == "1":
        sweep()
        return 0
    start_sweep()
    line = note(read_state(), shutil.disk_usage(HOME))
    if line:
        print(json.dumps({"systemMessage": line,
                          "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # fail open: a disk note never stops a session
        sys.exit(0)

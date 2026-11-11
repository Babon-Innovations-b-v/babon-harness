#!/usr/bin/env python3
"""The push cap: a push to main is refused once the day's pushes to main reach the day's limit, counted over every
repository on this machine that reads the same cap config.

Each push to main starts a gate run somewhere, and a gate run costs money; a day's limit keeps work batched into few
pushes. The shared pre-push hook runs `claim` before the repository's own pre-push and `release` when that one refused
the push, so a refused push holds no slot. A push the remote refused (git has no hook after the transfer) gives its
slot back at the next claim from this repository: an earlier push of this repository, at least SETTLE_SECONDS old,
whose commit git holds and which origin's main (refs/remotes/origin/main, moved by every push the remote took) does
not contain, never reached main (a push the remote refused, say as not a fast-forward, would otherwise hold its
slot). A push git cannot judge (its commit not here, no origin/main) keeps its slot.

    push_cap.py claim     push lines on stdin; exit 1 (and why on stderr) when today's limit is reached, else 0
                          with the push recorded in the ledger
    push_cap.py release   push lines on stdin; takes this push's claim back out of the ledger

THE CONFIG is JSON at $HARNESS_PUSH_CAP, else ~/.config/harness/push-cap.json; with no file there is no cap:

    {"limits": [{"from": "2026-01-01", "per_day": 6}, {"from": "2026-02-01", "per_day": 4}],
     "ledger": "~/.config/harness/push-cap-ledger.json", "uncounted": ["releases"]}

Days are UTC. Today's limit is the `per_day` of the latest entry whose `from` is today or earlier; none, or a
`per_day` of null, is no cap. `ledger` defaults to push-cap-ledger.json beside the config; every repository naming
the same ledger shares one count. The ledger keeps 14 days of pushes: {"<day>": [{"repo", "sha", "at"}]}.

`uncounted` lists release-only repositories, each by its name (the last part of its origin url or top folder, without
.git) or its whole url: a release push there starts no gate run, so it passes and is not counted (counted, release
pushes would use up gate slots and block a release). Deletions and pushes to tags or other branches (a release tag or
branch included) pass at once and are not counted. FAILURE POLICY: a config or ledger that
exists but cannot be read is a refusal naming the file (a cap someone set is never skipped silently); a push line
that cannot be read is no push to main.
"""
import datetime
import fcntl
import json
import os
import pathlib
import subprocess
import sys

ZERO = "0" * 40
KEEP_DAYS = 14
SETTLE_SECONDS = 300  # a push claimed this recently may still be on its way to the remote: never judged refused
REMOTE_MAIN = "refs/remotes/origin/main"


def config_path():
    """Where the cap config is looked for."""
    return pathlib.Path(os.environ.get("HARNESS_PUSH_CAP") or pathlib.Path.home() / ".config/harness/push-cap.json")


def pushed_to_main(lines):
    """The local sha of the push line updating refs/heads/main, or None (a deletion counts as none)."""
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2] == "refs/heads/main" and parts[1] != ZERO:
            return parts[1]
    return None


def limit_for(limits, day):
    """The per_day limit of the latest entry starting on or before `day` (ISO dates compare as text), or None."""
    started = [entry for entry in limits if str(entry["from"]) <= day]
    return max(started, key=lambda entry: str(entry["from"]))["per_day"] if started else None


def repository():
    """This repository's name for the ledger: its origin url, else its top folder."""
    for args in (["config", "--get", "remote.origin.url"], ["rev-parse", "--show-toplevel"]):
        done = subprocess.run(["git", *args], capture_output=True, text=True)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return os.getcwd()


def uncounted(here, names):
    """True when the repository `here` (url or folder) is listed in `names` by its name or in full."""
    name = here.rstrip("/").replace(":", "/").rsplit("/", 1)[-1].removesuffix(".git")
    return here in names or name in names


def read_ledger(handle):
    """The ledger's days from its open handle ({} when empty); raises ValueError when it is not a ledger."""
    handle.seek(0)
    text = handle.read()
    days = json.loads(text) if text.strip() else {}
    if not isinstance(days, dict):
        raise ValueError("not a JSON object")
    return days


def write_ledger(handle, days):
    """Replace the ledger's content with the newest KEEP_DAYS days."""
    kept = dict(sorted(days.items())[-KEEP_DAYS:])
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(kept, indent=1, sort_keys=True) + "\n")
    handle.flush()


def refused(why):
    """Say why the push is refused; the exit code that refuses it."""
    print(f"push cap: refused, {why}", file=sys.stderr)
    return 1


def git_answer(*args):
    """git's exit code for `args` in this repository."""
    return subprocess.run(["git", *args], capture_output=True, text=True).returncode


def never_reached_main(push, here, now):
    """True when `push` is this repository's, settled, and git proves origin's main does not hold its commit."""
    if push.get("repo") != here:
        return False
    waited = datetime.datetime.fromisoformat(now) - datetime.datetime.fromisoformat(push["at"])
    if waited.total_seconds() < SETTLE_SECONDS:
        return False
    if git_answer("cat-file", "-e", f"{push['sha']}^{{commit}}") or git_answer("rev-parse", "-q", "--verify",
                                                                                 REMOTE_MAIN):
        return False
    return git_answer("merge-base", "--is-ancestor", push["sha"], REMOTE_MAIN) == 1


def claim(sha, limits, ledger, day, now):
    """Record this push in the ledger when today's count is under the limit, after giving back the slots of this
    repository's pushes the remote refused; the exit code."""
    here = repository()
    with open(ledger, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        days = read_ledger(handle)
        today = [push for push in days.get(day, []) if not never_reached_main(push, here, now)]
        cap = limit_for(limits, day)
        if cap is not None and len(today) >= cap:
            pushes = "; ".join(f"{push['at'][11:16]} {push['repo']} {push['sha'][:12]}" for push in today)
            return refused(f"{len(today)} pushes to main today ({day} UTC) reached today's limit of {cap}, counted over "
                           f"every repository sharing {ledger} ({pushes}). Gather the work into one push after "
                           f"00:00 UTC, or change the limit in {config_path()} with the owner's yes.")
        days[day] = today + [{"repo": here, "sha": sha, "at": now}]
        write_ledger(handle, days)
    print(f"push cap: push {len(today) + 1} of {cap if cap is not None else 'no limit'} today ({day} UTC)",
          file=sys.stderr)
    return 0


def release(sha, ledger, day):
    """Take this push's claim (today's last entry for this sha) back out of the ledger."""
    if not ledger.exists():
        return 0
    with open(ledger, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        days = read_ledger(handle)
        today = days.get(day, [])
        mine = [index for index, push in enumerate(today) if push.get("sha") == sha]
        if mine:
            del today[mine[-1]]
            days[day] = today
            write_ledger(handle, days)
    return 0


def main():
    """claim or release, as argv[1] says, for the push lines on stdin."""
    verb = sys.argv[1] if len(sys.argv) > 1 else ""
    sha = pushed_to_main(sys.stdin.read())
    path = config_path()
    if verb not in ("claim", "release") or sha is None or not path.exists():
        return 0
    try:
        config = json.loads(path.read_text())
        limits = config["limits"]
        ledger = pathlib.Path(os.path.expanduser(config.get("ledger") or path.parent / "push-cap-ledger.json"))
        release_only = list(config.get("uncounted") or [])
    except (OSError, ValueError, KeyError, TypeError) as error:
        return refused(f"the push cap config {path} cannot be read ({error!r}); fix it or move it away")
    if uncounted(repository(), release_only):
        return 0
    moment = datetime.datetime.now(datetime.timezone.utc)
    day = moment.date().isoformat()
    try:
        if verb == "claim":
            return claim(sha, limits, ledger, day, moment.isoformat(timespec="seconds"))
        return release(sha, ledger, day)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return refused(f"the push cap ledger {ledger} cannot be read or written ({error!r})")


if __name__ == "__main__":
    sys.exit(main())

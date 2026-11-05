"""A verifying run's verdict is only about the suite the deploy cycle runs, and reaches the cycle unaltered.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

WHAT IT PINS. The refusal at the top of `commit_gate/run_one.sh`: the run reads
the gate's `--ignore` list out of the commit under test AND out of the clone the
cycle sources its steps from, and refuses (exit 79) unless the two are equal.

WHY. The cycle runs the suite its clone's 40-gate.sh names, while a verifying
run tests an older commit that may name another. The verdict cache key (sha,
scope, tree) cannot see the difference, so a verdict about a different suite
would be replayed as the cycle's own.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Real git
repositories are built whose two step files agree, disagree, or name no list,
and the shipped refusal is extracted and run against each. The expected exit
code follows from the rule above.

WHAT IT WAS PROVED AGAINST. Comparing only the commit's list with itself, so a
mismatch with the clone falls through.

THE LANE'S HAND-OFF. The cases after the refusal pin the rest of the drawer:
the ConfigMap the lane publishes (`lane_drawers.py`) carries only the queued
commits and never overwrites a file the cycle holds; a burst (`batch.sh`) is
halved only while red until one commit is red on its own; and the lane in the
cluster (`cluster_lane.sh`) takes no bookmark that is not a full sha.

THE DRAIN. `dispatch.sh` gives a commit pushed while a pass runs a pass of its
own at once when a second slot is free (`COMMIT_GATE_PASSES`), and makes it
wait for the running pass when there is none; a commit a red batch took but
never ran is taken again by the same drain. The shipped dispatcher runs over a
real git repository with a stand-in `verify_ahead.sh` that records when it
starts and ends each commit; the expected order is written from the rule.

GUARDS. The verdict cache.
"""
from __future__ import annotations

import inspect


# From a commit gate run refuses a commit whose suite is not the cycles.

import json
import shutil
import subprocess
import sys


from pathlib import Path


import pytest


_LANE = Path(__file__).resolve().parents[1] / "commit_gate" / "run_one.sh"


#: The line the refusal opens on: the path of the step file it compares.
_GUARD_OPENS = 'GATE_STEP_PATH="infra/auto-deploy/steps/40-gate.sh"'


#: The last line of the refusal. Both arms exit 79; this closes the second.
_GUARD_CLOSES = "fi"


#: What a `40-gate.sh` has to contain for the comparison to have an answer.
#: Only the `--ignore=` flags are read, so the rest of the file is not modelled.
_IGNORES_A = "pytest --ignore=.claude/worktrees --ignore=vendor\n"


_IGNORES_B = "pytest --ignore=.claude/worktrees\n"


def _guard() -> str:
    """The refusal: the `GATE_STEP_PATH` line to the `fi` that closes it.

    Found by its own two `exit 79` arms rather than by counting keywords, for
    the same reason the step-40 chain test gives: a regex for the first `fi`
    stops inside the first arm and silently tests half the thing.
    """
    lines = _LANE.read_text(encoding="utf-8").splitlines()
    starts = [index for index, line in enumerate(lines) if line == _GUARD_OPENS]
    assert len(starts) == 1, f"expected one ignore-list refusal in {_LANE}, found {len(starts)}"

    arms = [
        index
        for index, line in enumerate(lines)
        if line.strip() == "exit 79" and index > starts[0]
    ]
    assert len(arms) == 2, f"the refusal in {_LANE} has {len(arms)} arms, expected 2"

    for index in range(arms[-1], len(lines)):
        if lines[index] == _GUARD_CLOSES:
            return "\n".join(lines[starts[0]: index + 1])
    raise AssertionError(f"the ignore-list refusal in {_LANE} never closes")


def _git(repo: Path, *args: str) -> str:
    """One git command in one repository, failing loudly."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return done.stdout.strip()


def _repo_with_two_gate_files(tmp_path: Path, committed: str, on_disk: str) -> tuple[Path, str]:
    """A clone whose HEAD `40-gate.sh` differs from the commit under test's.

    Returns the clone and the sha of the commit under test. `committed` is what
    that commit's step file says; `on_disk` is what the clone's working tree
    says, which is what the cycle would run.
    """
    repo = tmp_path / "clone"
    step = repo / "infra" / "auto-deploy" / "steps"
    step.mkdir(parents=True)
    (step / "40-gate.sh").write_text(committed, encoding="utf-8")
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the commit the lane is testing")
    sha = _git(repo, "rev-parse", "HEAD")

    if on_disk != committed:
        (step / "40-gate.sh").write_text(on_disk, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "the commit the clone has moved to")
    return repo, sha


def _run_guard(tmp_path: Path, repo: Path, sha: str) -> int:
    """Run the shipped refusal against one repository. Returns its exit code.

    `0` means it fell through, which is the lane going on to produce a verdict.
    """
    script = "\n".join((
        "set -u",
        'log() { :; }',
        f'REPO="{repo}"',
        f'SHA="{sha}"',
        _guard(),
        "exit 0",
    ))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    return done.returncode


def _a_run_whose_suite_is_the_cycles_suite_goes_on(tmp_path: Path) -> None:
    """Both lists the same is the ordinary case, and it must not be refused.

    Without this the other cases pass for a refusal that refuses everything,
    which would stop the lane producing any verdict at all.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, _IGNORES_A, _IGNORES_A)
    assert _run_guard(tmp_path, repo, sha) == 0


def _a_run_whose_ignore_list_came_from_another_commit_is_refused(
    tmp_path: Path,
) -> None:
    """The commit says one suite and the clone says another, so neither is safe.

    This is the whole failure: the verdict would be about a suite the cycle does
    not run, and nothing downstream could tell, because the cache key does not
    carry the list.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, _IGNORES_A, _IGNORES_B)
    assert _run_guard(tmp_path, repo, sha) == 79


def _a_run_that_cannot_read_both_lists_is_refused(
    tmp_path: Path, committed: str, on_disk: str
) -> None:
    """Unreadable is not the same as equal, and it may not be treated as equal.

    An empty list on either side means the comparison has no answer, so the run
    cannot know which suite it is. It refuses rather than guessing.
    """
    repo, sha = _repo_with_two_gate_files(tmp_path, committed, on_disk)
    assert _run_guard(tmp_path, repo, sha) == 79


def _the_only_clone_file_the_lane_opens_is_the_one_it_compares() -> None:
    """A second clone read is a second way for the two commits to differ.

    The refusal above closes exactly one hole: the ignore list. Every other file
    the lane needs comes out of `$WORK`, the export of the commit under test, so
    a new `$REPO/`-rooted file read is a new mismatch nothing checks. Reads that
    name a sha (`git -C "$REPO" show|archive|ls-tree <sha>`) are object reads and
    are not this: they are immutable, and a working tree is not.
    """
    lines = _LANE.read_text(encoding="utf-8").splitlines()
    opened = [
        line.strip()
        for line in lines
        if '"$REPO/' in line and not line.lstrip().startswith("#")
    ]
    assert opened == ['CLONE_IGNORES="$(_cg_ignore_flags < "$REPO/$GATE_STEP_PATH" 2>/dev/null)"'], (
        "run_one.sh reads a file out of the clone that the ignore-list refusal "
        f"does not compare: {opened}"
    )



_DRAWER = Path(__file__).resolve().parents[1] / "commit_gate"


def _drawers(*argv: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_DRAWER / "lane_drawers.py"), *argv], input=stdin,
                          capture_output=True, text=True, check=False, timeout=60)


def _the_lane_publishes_only_queued_commits_and_the_cycle_never_replaces_a_file_it_holds(tmp_path: Path) -> None:
    """The lane's ConfigMap carries the queue's drawer files; unpacking adds, it never overwrites.

    A verdict the cycle already holds may be the one it shipped on, so a copy
    from the lane must not replace it; a key naming no drawer, or a verdict
    line about another commit, is refused.
    """
    queued, passed, other = "1" * 40, "2" * 40, "3" * 40
    lane = tmp_path / "lane"
    (lane / "gate-verdicts").mkdir(parents=True)
    (lane / "gate-scopes").mkdir()
    (lane / "gate-verdicts" / queued).write_text(f"{queued} green selected 1 replayed t\n", encoding="utf-8")
    (lane / "gate-verdicts" / passed).write_text(f"{passed} green selected 1 replayed t\n", encoding="utf-8")
    (lane / "gate-scopes" / f"{queued}.json").write_text("{}", encoding="utf-8")
    (tmp_path / "shas").write_text(queued + "\n", encoding="utf-8")
    packed = _drawers("pack", "--state-dir", str(lane), "--shas-file", str(tmp_path / "shas"),
                      "--name", "commit-gate-verdicts", "--namespace", "deploy")
    document = json.loads(packed.stdout)
    assert sorted(document["data"]) == [f"s.{queued}", f"v.{queued}"]

    cycle = tmp_path / "cycle"
    (cycle / "gate-verdicts").mkdir(parents=True)
    (cycle / "gate-verdicts" / queued).write_text("the cycle's own line\n", encoding="utf-8")
    document["data"]["x." + other] = "no such drawer"
    document["data"]["v." + other] = f"{passed} green selected 1 replayed t\n"
    unpacked = _drawers("unpack", "--state-dir", str(cycle), stdin=json.dumps(document))
    assert unpacked.stdout.strip() == "1"
    assert (cycle / "gate-verdicts" / queued).read_text(encoding="utf-8") == "the cycle's own line\n"
    assert (cycle / "gate-scopes" / f"{queued}.json").read_text(encoding="utf-8") == "{}"
    assert not (cycle / "gate-verdicts" / other).exists()


_FAKE_RUN_ONE = """#!/bin/bash
# Stand-in for run_one.sh: red when the range it is asked about holds a red commit.
printf '%s %s\\n' "$1" "${COMMIT_GATE_BATCH_BASE:--}" >> "$CALLS"
range="$1"
[ -n "${COMMIT_GATE_BATCH_BASE:-}" ] && range="$(cat "$RANGES/$COMMIT_GATE_BATCH_BASE-$1")"
for sha in $range; do
    grep -qx "$sha" "$REDS" && exit 1
done
exit 0
"""


def _a_batch_is_split_only_while_red_down_to_the_one_red_commit(tmp_path: Path, reds: list, calls: list) -> None:
    """A burst is verified once on its newest commit and halved only while red.

    Five made-up commits on a base; the stand-in run_one.sh is red exactly when
    the range it is given holds a red commit. The calls expected are the
    halving worked by hand: a green half moves the base past it, a red half is
    split again, and the search ends on the one red commit asked on its own.
    """
    shutil.copy(_DRAWER / "batch.sh", tmp_path / "batch.sh")
    (tmp_path / "run_one.sh").write_text(_FAKE_RUN_ONE, encoding="utf-8")
    commits = [f"c{index}" for index in range(1, 6)]
    ranges = tmp_path / "ranges"
    ranges.mkdir()
    for low, base in enumerate(["base", *commits]):
        for high in range(low, len(commits)):
            (ranges / f"{base}-{commits[high]}").write_text(" ".join(commits[low:high + 1]), encoding="utf-8")
    (tmp_path / "reds").write_text("".join(f"{red}\n" for red in reds), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "CALLS": str(tmp_path / "calls"), "RANGES": str(ranges),
           "REDS": str(tmp_path / "reds")}
    subprocess.run(["bash", str(tmp_path / "batch.sh"), "base", *commits], env=env, capture_output=True,
                   text=True, check=True, timeout=60)
    assert (tmp_path / "calls").read_text(encoding="utf-8").splitlines() == calls


_FAKE_KUBECTL_BOOKMARK = """#!/bin/bash
printf '%s' "$BOOKMARK_VALUE"
"""


def _the_lane_takes_no_bookmark_that_is_not_a_full_sha(tmp_path: Path, value: str, taken: bool) -> None:
    """No bookmark is no range: the lane verifies nothing rather than the whole history."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").write_text(_FAKE_KUBECTL_BOOKMARK, encoding="utf-8")
    (bin_dir / "kubectl").chmod(0o755)
    state = tmp_path / "state"
    script = f'. "{_DRAWER / "cluster_lane.sh"}"; lane_pull_bookmark'
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin", "STATE_DIR": str(state), "BOOKMARK_VALUE": value})
    assert (done.returncode == 0) is taken
    written = state / "last-deployed-sha"
    assert (written.read_text(encoding="utf-8").strip() == value) if taken else not written.exists()


#: A stand-in for `verify_ahead.sh`, driven by FAKE_MODE. `push`: takes the
#: oldest commit no pass took or answered, and while it runs commit A a commit
#: B lands on main. `batch-red`: takes every such commit at once, and only the
#: first gets a run, which is red, as `batch.sh` leaves a range whose first
#: commit broke. Every pass appends what it did to $EVENTS, by commit subject.
_FAKE_VERIFY_AHEAD = r"""#!/bin/bash
set -u
R="$COMMIT_GATE_REPO"
name() { git -C "$R" log -1 --format=%s "$1"; }
todo=()
for sha in $(git -C "$R" rev-list --reverse "$(cat "$STATE_DIR/last-deployed-sha")..main"); do
    grep -qxF "$sha" "$COMMIT_GATE_SKIP_FILE" 2>/dev/null && continue
    [ -e "$STATE_DIR/gate-verdicts/$sha" ] && continue
    todo+=("$sha")
done
[ "${#todo[@]}" -gt 0 ] || exit 0
[ "$FAKE_MODE" = "push" ] && todo=("${todo[0]}")
printf '%s\n' "${todo[@]}" > "$COMMIT_GATE_TAKEN_FILE.tmp"
mv "$COMMIT_GATE_TAKEN_FILE.tmp" "$COMMIT_GATE_TAKEN_FILE"
first="${todo[0]}"
if [ "$FAKE_MODE" = "batch-red" ]; then
    echo "take $(for sha in "${todo[@]}"; do name "$sha"; done | tr '\n' ' ' | sed 's/ $//')" >> "$EVENTS"
    verdict=green; [ "${#todo[@]}" -gt 1 ] && verdict=red
    [ "$verdict" = red ] && echo "$first 1" >> "$COMMIT_GATE_OUTCOME_FILE"
else
    echo "start $(name "$first")" >> "$EVENTS"
    if [ "$(name "$first")" = A ]; then
        git -C "$R" commit -q --allow-empty -m B
        sleep 0.4
    fi
    echo "end $(name "$first")" >> "$EVENTS"
    verdict=green
fi
echo "$first $verdict selected 1 none $(git -C "$R" rev-parse "$first^{tree}")" > "$STATE_DIR/gate-verdicts/$first"
exit 0
"""


def _the_drain_gives_a_pushed_commit_a_pass_of_its_own_while_a_slot_is_free(
        tmp_path: Path, mode: str, passes: int, events: list) -> None:
    """What the shipped dispatcher made the stand-in do, in order, is what the rule says."""
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "deployed")
    bookmark = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "A")
    if mode == "batch-red":
        _git(repo, "commit", "-q", "--allow-empty", "-m", "B")
    drawer = tmp_path / "commit_gate"
    drawer.mkdir()
    (tmp_path / "steps").mkdir()
    shutil.copy(_DRAWER / "dispatch.sh", drawer / "dispatch.sh")
    shutil.copy(_DRAWER.parent / "steps" / "doors.sh", tmp_path / "steps" / "doors.sh")
    (drawer / "verify_ahead.sh").write_text(_FAKE_VERIFY_AHEAD, encoding="utf-8")
    state = tmp_path / "state"
    (state / "gate-verdicts").mkdir(parents=True)
    (state / "last-deployed-sha").write_text(bookmark + "\n", encoding="utf-8")
    recorded = tmp_path / "events"
    recorded.touch()
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
        "HARNESS_ROOT": str(tmp_path / "harness"), "HARNESS_ENV_FILE": str(tmp_path / "none.env"),
        "COMMIT_GATE_REPO": str(repo), "STATE_DIR": str(state), "COMMIT_GATE_LOG": str(tmp_path / "log"),
        "COMMIT_GATE_ROOT": str(tmp_path / "root"), "COMMIT_GATE_BRANCH": "main",
        "COMMIT_GATE_PASSES": str(passes), "COMMIT_GATE_POLL_SECONDS": "0.1",
        "FAKE_MODE": mode, "EVENTS": str(recorded),
    }
    subprocess.run(["bash", str(drawer / "dispatch.sh")], env=env, capture_output=True,
                   text=True, check=False, timeout=60)
    assert recorded.read_text(encoding="utf-8").splitlines() == events


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_run_whose_suite_is_the_cycles_suite_goes_on),
    *_cases(_a_run_whose_ignore_list_came_from_another_commit_is_refused),
    *_cases(_a_run_that_cannot_read_both_lists_is_refused, 
    ("committed", "on_disk"),
    [
        pytest.param("pytest -q\n", _IGNORES_A, id="the commit names no ignore list"),
        pytest.param(_IGNORES_A, "pytest -q\n", id="the clone names no ignore list"),
    ],
),
    *_cases(_the_only_clone_file_the_lane_opens_is_the_one_it_compares),
    *_cases(_the_lane_publishes_only_queued_commits_and_the_cycle_never_replaces_a_file_it_holds),
    *_cases(_a_batch_is_split_only_while_red_down_to_the_one_red_commit, ("reds", "calls"), [
        pytest.param([], ["c5 base"], id="a green burst is one run"),
        pytest.param(["c3"], ["c5 base", "c2 base", "c5 c2", "c3 -"], id="the red in the middle is found alone"),
        pytest.param(["c1"], ["c5 base", "c2 base", "c1 -"], id="the red first commit is found alone"),
        pytest.param(["c5"], ["c5 base", "c2 base", "c5 c2", "c3 -", "c5 c3", "c4 -", "c5 -"],
                     id="the red newest commit is found alone"),
    ]),
    *_cases(_the_drain_gives_a_pushed_commit_a_pass_of_its_own_while_a_slot_is_free, ("mode", "passes", "events"), [
        pytest.param("push", 2, ["start A", "start B", "end B", "end A"],
                     id="a commit pushed while a pass runs gets its own pass at once"),
        pytest.param("push", 1, ["start A", "end A", "start B", "end B"],
                     id="with one pass slot it waits for the pass"),
        pytest.param("batch-red", 1, ["take A B", "take B"],
                     id="a commit a red batch never ran is taken again in the same drain"),
    ]),
    *_cases(_the_lane_takes_no_bookmark_that_is_not_a_full_sha, ("value", "taken"), [
        pytest.param("a" * 40, True, id="a full sha"),
        pytest.param("", False, id="never seeded"),
        pytest.param("main", False, id="not a sha"),
    ]),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_commit_gate_run_refuses_a_commit_whose_suite_is_not_the_cycles(scenario, given, uses, request):
    """A verifying run's verdict is only about the suite the deploy cycle runs: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})

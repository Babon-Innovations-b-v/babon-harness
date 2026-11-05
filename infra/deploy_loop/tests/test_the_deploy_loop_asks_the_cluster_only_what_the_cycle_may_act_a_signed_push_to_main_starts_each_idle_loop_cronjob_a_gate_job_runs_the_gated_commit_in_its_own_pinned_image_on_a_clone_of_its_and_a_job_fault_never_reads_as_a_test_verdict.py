"""The deploy loop asks the cluster only what the cycle may act on: a signed push to main starts each idle loop CronJob once, a gate Job runs the gated commit in its own pinned image on a clone of its own, and a Job fault never reads as a test verdict.

WHAT IT PINS. `infra/deploy_loop` through its public names (`__all__`):
`push_should_trigger` and `cronjobs_to_start` (the receiver),
`gate_job_manifest` and `pinned_gate_image` (the Job), `gate_job_outcome`
(the Job read as an exit code), `read_shards` and `combined_rc` (one run as one
Job per module group), `bookmark_sha`, `image_targets` and `stack_images`, and
the `gate-run` verb against a stand-in `kubectl` that records what it is given.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Every input is
made up here: a secret and a body whose signature the test computes itself with
hmac, CronJob and Job documents written by hand in the shape `kubectl get -o
json` gives, Job and pod states for each row of the outcome table, a
ConfigMap, a list of Deployments, and a tiny tree with one manifest and one
compose fragment. Each answer is the rule in the module's docstring applied by
hand to that input. Nothing reads a cluster, a clock or the network.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. Reading a Job the deadline killed by its container's
exit code instead of as a timeout, which the deadline case catches.

GUARDS. The owner's rule that a red is the commit's or the test's, and a run
that could not finish is neither.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path

import pytest

from infra.deploy_loop import (
    baked_sum,
    bookmark_sha,
    build_decision,
    combined_rc,
    cronjobs_to_start,
    gate_job_manifest,
    gate_job_outcome,
    image_targets,
    judge_trial,
    pin_patches,
    pinned_gate_image,
    push_should_trigger,
    read_shards,
    stack_images,
    trusted_head,
)
from infra.deploy_loop._trust import Commit as _TrustCommit

_SECRET = "made-up-secret"
_SHA = "a" * 40
_DIGEST = "registry.example/ns/gate@sha256:" + "b" * 64


def _signed(body: bytes, secret: str = _SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push(ref: str) -> bytes:
    return json.dumps({"ref": ref, "head_commit": {"id": _SHA}}).encode()


def _a_push_starts_only_when_signed_and_on_main(secret, signature_of, ref, starts, tmp_path):
    body = _push(ref)
    signature = _signed(body, signature_of) if signature_of else ""
    assert push_should_trigger(secret, signature, body)[0] is starts


def _cronjob(name, suspend=False):
    return {"metadata": {"name": name}, "spec": {"suspend": suspend}}


def _job(owner, active):
    return {"metadata": {"ownerReferences": [{"kind": "CronJob", "name": owner}], "labels": {}},
            "status": {"active": active}}


def _a_push_starts_each_idle_loop_cronjob_once(tmp_path):
    cronjobs = {"items": [_cronjob("deploy-cycle"), _cronjob("commit-gate"), _cronjob("other"),
                          _cronjob("paused", suspend=True)]}
    jobs = {"items": [_job("commit-gate", 1), _job("deploy-cycle", 0)]}
    wanted = ["deploy-cycle", "commit-gate", "paused", "missing"]
    # deploy-cycle: present and its only Job finished; commit-gate: a Job is
    # active; paused: suspended; missing: no such CronJob.
    assert cronjobs_to_start(wanted, cronjobs, jobs) == ["deploy-cycle"]


def _pod(**status):
    return {"metadata": {"creationTimestamp": "2000-01-01T00:00:00Z"}, "status": status}


def _ended(code, reason="Error"):
    return {"containerStatuses": [{"state": {"terminated": {"exitCode": code, "reason": reason}}}]}


def _waiting(reason, message=""):
    return {"containerStatuses": [{"state": {"waiting": {"reason": reason, "message": message}}}]}


_FAILED = {"status": {"conditions": [{"type": "Failed", "status": "True"}]}}
_DEADLINE = {"status": {"conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]}}
_COMPLETE = {"status": {"conditions": [{"type": "Complete", "status": "True"}]}}
_RUNNING = {"status": {"active": 1}}


def _a_gate_job_reads_as_the_code_its_own_table_gives(job, pods, timed_out, pin_is_new, code, tmp_path):
    assert gate_job_outcome(job, pods, timed_out, pin_is_new) == code


def _a_gate_job_runs_the_gated_commit_in_its_pinned_image_with_no_token_in_the_run(tmp_path):
    manifest = gate_job_manifest(
        name="gate-x", namespace="deploy", sha=_SHA, repo_url="https://example.invalid/r.git",
        gate_image=_DIGEST, cycle_image="registry.example/ns/deploy-cycle:v1", pool_label="harness/role",
        pytest_args=["-q", "tests/a"], seconds=600, setup_seconds=300, changed_paths="a/b.py\n",
    )
    spec = manifest["spec"]
    pod = spec["template"]["spec"]
    run, fetch = pod["containers"][0], pod["initContainers"][0]
    assert spec["activeDeadlineSeconds"] == 900 and spec["backoffLimit"] == 0
    assert run["image"] == _DIGEST and run["command"][-2:] == ["-q", "tests/a"]
    assert pod["nodeSelector"] == {"harness/role": "gate"}
    assert pod["automountServiceAccountToken"] is False and pod["priorityClassName"] == "deploy-loop"
    assert [mount["name"] for mount in run["volumeMounts"]] == ["work"]
    assert "git-read" in [mount["name"] for mount in fetch["volumeMounts"]]
    assert not any("persistentVolumeClaim" in volume for volume in pod["volumes"])
    script = run["command"][2]
    assert "$" not in script.replace("$$", ""), "every $ reaches Kubernetes doubled"


def _a_gate_job_refuses_an_image_not_pinned_by_digest(image, tmp_path):
    with pytest.raises(ValueError):
        gate_job_manifest(name="g", namespace="d", sha=_SHA, repo_url="u", gate_image=image, cycle_image="c",
                          pool_label="l", pytest_args=["-q"], seconds=1, setup_seconds=1)


def _the_pin_names_an_image_only_by_digest(text, image, tmp_path):
    assert pinned_gate_image(text) == image


def _the_bookmark_is_a_full_sha_or_none_yet_and_nothing_else(data, answer, tmp_path):
    if answer is ValueError:
        with pytest.raises(ValueError):
            bookmark_sha({"data": data} if data is not None else {})
    else:
        assert bookmark_sha({"data": data}) == answer


def _deployment(namespace, name, image):
    return {"kind": "Deployment", "metadata": {"namespace": namespace, "name": name},
            "spec": {"template": {"spec": {"containers": [{"name": "app", "image": image}]}}}}


def _a_new_image_is_set_on_every_object_running_another_tag_of_it(tmp_path):
    built = "registry.example:5000/ns/web:git-abc@sha256:" + "c" * 64
    documents = [{"kind": "List", "items": [
        _deployment("web", "old", "registry.example:5000/ns/web:set-by-deploy-loop"),
        _deployment("web", "done", built),
        _deployment("other", "unrelated", "registry.example:5000/ns/webby:1"),
    ]}]
    assert image_targets(documents, built) == [("web", "deployment", "old", "app")]


def _a_stack_image_is_built_from_the_compose_service_of_its_name(tmp_path):
    (tmp_path / "infra/k8s/web").mkdir(parents=True)
    (tmp_path / "infra/k8s/web/web.yaml").write_text(
        "image: ${IMAGE_REGISTRY}/site:set-by-deploy-loop\nimage: ${IMAGE_REGISTRY}/lonely:set-by-deploy-loop\n",
        encoding="utf-8")
    (tmp_path / "apps/site").mkdir(parents=True)
    (tmp_path / "apps/site/compose.yml").write_text(
        "services:\n  site:\n    build:\n      context: ../..\n      dockerfile: apps/site/Dockerfile\n"
        "    restart: always\n", encoding="utf-8")
    assert stack_images(tmp_path) == [
        {"name": "lonely", "context": "", "dockerfile": ""},
        {"name": "site", "context": ".", "dockerfile": "apps/site/Dockerfile"},
    ]


def _shards_add_up_to_the_code_one_pytest_would_give(codes, code, tmp_path):
    assert combined_rc(codes) == code


def _a_shards_file_is_read_as_shards_in_first_seen_order(tmp_path):
    text = "b\tpkg/b/tests\na\tpkg/a/tests\n\nno-tab-line\nb\tpkg/b/more\n\t\n"
    assert read_shards(text) == [("b", ["pkg/b/tests", "pkg/b/more"]), ("a", ["pkg/a/tests"])]


_FAKE_KUBECTL = """#!/bin/bash
# A stand-in kubectl: records every Job it is given, and says each one ended 0.
[ "$1" = "-n" ] && shift 2
case "$1 $2" in
  "apply -f") cat > "$JOBS/$(date +%s%N).json"; exit 0 ;;
  "get job") printf '%s' '{"status": {"conditions": [{"type": "Complete", "status": "True"}], "succeeded": 1}}' ;;
  "get pods") printf '%s' '{"items": [{"status": {"phase": "Succeeded", "containerStatuses": [{"name": "run", "state": {"terminated": {"exitCode": 0}}}]}}]}' ;;
  "logs job/"*|logs*) echo "1 passed" ;;
esac
"""


def _a_shards_file_makes_one_job_per_shard_and_only_the_first_replays(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "kubectl").write_text(_FAKE_KUBECTL, encoding="utf-8")
    (tmp_path / "bin" / "kubectl").chmod(0o755)
    (tmp_path / "pin").write_text(_DIGEST + "\n", encoding="utf-8")
    (tmp_path / "changed").write_text("pkg/a/code.py\n", encoding="utf-8")
    (tmp_path / "shards").write_text("a\tpkg/a/tests\nb\tpkg/b/tests\n", encoding="utf-8")
    answer = subprocess.run(
        [sys.executable, "-m", "infra.deploy_loop", "gate-run", "--sha", _SHA, "--repo-url", "https://example/r.git",
         "--gate-pin", str(tmp_path / "pin"), "--cycle-image", _DIGEST, "--pool-label", "role", "--seconds", "60",
         "--changed-file", str(tmp_path / "changed"), "--shards-file", str(tmp_path / "shards"),
         "--", "-q", "-rfE"],
        cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "JOBS": str(jobs)},
    )
    made = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(jobs.iterdir())]
    runs = [job["spec"]["template"]["spec"]["containers"][0] for job in made]
    assert answer.returncode == 0, answer.stderr
    assert [run["command"][-1] for run in runs] == ["pkg/a/tests", "pkg/b/tests"]
    assert [{var["name"]: var["value"] for var in run["env"]}["GATE_CHANGED_PATHS"] for run in runs] == ["pkg/a/code.py\n", ""]



# The trust walk (`_trust.py`): commits are made up as (sha, tree, verdict line).
_T = "e" * 40


def _commit(letter, verdict="", reverts=""):
    sha = letter * 40
    return _TrustCommit(sha, _T, verdict.format(sha=sha, tree=_T), reverts)


def _the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers(commits, scope_none, licensed,
                                                                         head, reason, tmp_path):
    answer = trusted_head(commits, lambda commit: commit.sha in scope_none, licensed=licensed)
    assert (answer.head, answer.reason) == (head, reason)


_GREEN = "{sha} green selected 1 replayed {tree}"
_GREEN_FULL = "{sha} green full 1 replayed {tree}"
_BATCH = "{sha} green selected 1 batch:cccccccccccc {tree}"
_PLAIN = "{sha} green selected 1 none {tree}"
_RED = "{sha} red selected 1 regression {tree}"
_OTHER_TREE = "{sha} green selected 1 replayed " + "f" * 40


def _the_baked_sum_moves_with_what_the_image_runs_and_not_with_its_tests_or_notes(tmp_path):
    (tmp_path / "infra/deploy_loop/image").mkdir(parents=True)
    (tmp_path / "infra/deploy_loop/tests").mkdir()
    (tmp_path / "infra/deploy_loop/_x.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "infra/deploy_loop/image/Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    before = baked_sum(tmp_path)
    (tmp_path / "infra/deploy_loop/tests/test_x.py").write_text("def test(): pass\n", encoding="utf-8")
    (tmp_path / "infra/deploy_loop/CLAUDE.md").write_text("notes\n", encoding="utf-8")
    assert baked_sum(tmp_path) == before
    (tmp_path / "infra/deploy_loop/_x.py").write_text("x = 2\n", encoding="utf-8")
    assert baked_sum(tmp_path) != before


def _the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new(state, word, tmp_path):
    assert build_decision(state, "s1", now=1000.0, retry_seconds=600)[0] == word


def _cycle_job(image, created, condition=""):
    status = {"conditions": [{"type": condition, "status": "True"}]} if condition else {}
    return {"metadata": {"creationTimestamp": created},
            "spec": {"template": {"spec": {"containers": [{"name": "cycle", "image": image}]}}}, "status": status}


_OLD_IMAGE = "registry.example/ns/deploy-cycle:git-aaaaaaaaaaaa@sha256:" + "1" * 64
_NEW_IMAGE = "registry.example/ns/deploy-cycle:git-bbbbbbbbbbbb@sha256:" + "2" * 64
_TRIAL = {"good": _OLD_IMAGE, "candidate": _NEW_IMAGE, "candidate_since": "1000"}


def _the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long(
        state, cycle_image, jobs, now, action, tmp_path):
    assert judge_trial(state, cycle_image, jobs, now).action == action


def _a_promotion_moves_every_loop_object_and_its_image_setting_but_nothing_else(tmp_path):
    def cronjob(name, image, env_image):
        return {"kind": "CronJob", "metadata": {"name": name}, "spec": {"jobTemplate": {"spec": {"template": {
            "spec": {"containers": [{"name": "c", "image": image,
                                     "env": [{"name": "DEPLOY_CYCLE_IMAGE", "value": env_image}]}]}}}}}}
    listing = {"kind": "List", "items": [
        cronjob("deploy-cycle", _NEW_IMAGE, _NEW_IMAGE),
        cronjob("commit-gate", _OLD_IMAGE, _OLD_IMAGE),
        {"kind": "Deployment", "metadata": {"name": "buildkitd"},
         "spec": {"template": {"spec": {"containers": [{"name": "b", "image": "moby/buildkit:v1"}]}}}},
    ]}
    patches = pin_patches([listing], _NEW_IMAGE)
    assert [(kind, name) for kind, name, _ in patches] == [("cronjob", "commit-gate")]
    moved = json.loads(patches[0][2])["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert moved == {"name": "c", "image": _NEW_IMAGE, "env": [{"name": "DEPLOY_CYCLE_IMAGE", "value": _NEW_IMAGE}]}
    assert pin_patches([listing], _OLD_IMAGE, skip="cronjob/deploy-cycle") == []

CASES = [
    *[
        pytest.param(_shards_add_up_to_the_code_one_pytest_would_give, {"codes": codes, "code": code}, id=label)
        for label, codes, code in [
            ("all-green", [0, 0], 0), ("one-red", [0, 1], 1), ("red-beats-amber", [137, 1], 1),
            ("lowest-broken-tree", [0, 3, 2], 2), ("amber-is-amber", [0, 124], 124), ("all-empty", [5, 5], 5),
            ("one-empty-beside-tests", [5, 0], 0), ("no-shard", [], 125), ("one-job", [126], 126),
        ]
    ],
    pytest.param(_a_shards_file_is_read_as_shards_in_first_seen_order, {}, id="shards-file"),
    pytest.param(_a_shards_file_makes_one_job_per_shard_and_only_the_first_replays, {}, id="one-job-per-shard"),
    pytest.param(_a_push_starts_only_when_signed_and_on_main,
                 {"secret": _SECRET, "signature_of": _SECRET, "ref": "refs/heads/main", "starts": True}, id="signed-main"),
    pytest.param(_a_push_starts_only_when_signed_and_on_main,
                 {"secret": _SECRET, "signature_of": "other", "ref": "refs/heads/main", "starts": False}, id="wrong-signature"),
    pytest.param(_a_push_starts_only_when_signed_and_on_main,
                 {"secret": "", "signature_of": "", "ref": "refs/heads/main", "starts": False}, id="no-secret"),
    pytest.param(_a_push_starts_only_when_signed_and_on_main,
                 {"secret": _SECRET, "signature_of": _SECRET, "ref": "refs/heads/branch", "starts": False}, id="not-main"),
    pytest.param(_a_push_starts_each_idle_loop_cronjob_once, {}, id="idle-cronjobs"),
    *[
        pytest.param(_a_gate_job_reads_as_the_code_its_own_table_gives,
                     {"job": job, "pods": pods, "timed_out": timed_out, "pin_is_new": pin_is_new, "code": code}, id=label)
        for label, job, pods, timed_out, pin_is_new, code in [
            ("deadline-before-exit-code", _DEADLINE, [_pod(**_ended(0))], False, False, 124),
            ("evicted", _FAILED, [_pod(reason="Evicted", **_ended(1))], False, False, 125),
            ("fetch-failed", _FAILED, [_pod(initContainerStatuses=[{"state": {"terminated": {"exitCode": 1}}}])], False, False, 125),
            ("pin-missing-new", _RUNNING, [_pod(**_waiting("ErrImagePull", "manifest unknown"))], False, True, 4),
            ("pin-missing-inherited", _RUNNING, [_pod(**_waiting("ErrImagePull", "manifest unknown"))], False, False, 125),
            ("oom", _FAILED, [_pod(**_ended(137, "OOMKilled"))], False, False, 137),
            ("suite-red", _FAILED, [_pod(**_ended(1))], False, False, 1),
            ("suite-green", _COMPLETE, [_pod(**_ended(0))], False, False, 0),
            ("failed-no-pod", _FAILED, [], False, False, 125),
            ("still-running", _RUNNING, [_pod(phase="Running")], False, False, None),
            ("caller-deadline", _RUNNING, [_pod(phase="Pending")], True, False, 124),
        ]
    ],
    pytest.param(_a_gate_job_runs_the_gated_commit_in_its_pinned_image_with_no_token_in_the_run, {}, id="job-shape"),
    pytest.param(_a_gate_job_refuses_an_image_not_pinned_by_digest, {"image": "registry.example/ns/gate:git-123"}, id="tag-refused"),
    pytest.param(_a_gate_job_refuses_an_image_not_pinned_by_digest, {"image": ""}, id="none-refused"),
    pytest.param(_the_pin_names_an_image_only_by_digest, {"text": "# c\n# built from: x\n" + _DIGEST + "\n", "image": _DIGEST}, id="pin-digest"),
    pytest.param(_the_pin_names_an_image_only_by_digest, {"text": "# built from:\n", "image": ""}, id="pin-empty"),
    pytest.param(_the_bookmark_is_a_full_sha_or_none_yet_and_nothing_else, {"data": {"sha": _SHA}, "answer": _SHA}, id="bookmark-sha"),
    pytest.param(_the_bookmark_is_a_full_sha_or_none_yet_and_nothing_else, {"data": {"sha": ""}, "answer": ""}, id="bookmark-none-yet"),
    pytest.param(_the_bookmark_is_a_full_sha_or_none_yet_and_nothing_else, {"data": None, "answer": ValueError}, id="bookmark-unseeded"),
    pytest.param(_the_bookmark_is_a_full_sha_or_none_yet_and_nothing_else, {"data": {"sha": "main"}, "answer": ValueError}, id="bookmark-not-a-sha"),
    pytest.param(_a_new_image_is_set_on_every_object_running_another_tag_of_it, {}, id="image-targets"),
    pytest.param(_a_stack_image_is_built_from_the_compose_service_of_its_name, {}, id="stack-images"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _GREEN), _commit("2", _GREEN)], "scope_none": set(), "licensed": True,
                  "head": "2" * 40, "reason": "all"}, id="trust-every-commit-replayed-green"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _GREEN), _commit("2"), _commit("3", _GREEN)], "scope_none": set(),
                  "licensed": True, "head": "1" * 40, "reason": "unanswered"}, id="trust-stops-at-an-unanswered-commit"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1"), _commit("2", _GREEN)], "scope_none": {"1" * 40}, "licensed": True,
                  "head": "2" * 40, "reason": "all"}, id="trust-a-commit-no-test-reaches-is-covered"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _BATCH), _commit("2", _BATCH)], "scope_none": set(), "licensed": True,
                  "head": "", "reason": "empty"}, id="trust-a-batch-member-is-never-the-head"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _BATCH), _commit("2", _GREEN)], "scope_none": set(), "licensed": True,
                  "head": "2" * 40, "reason": "all"}, id="trust-a-batch-is-covered-by-its-green-head"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _PLAIN)], "scope_none": set(), "licensed": True,
                  "head": "", "reason": "unreplayed"}, id="trust-a-green-without-its-replay-stops-the-walk"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _OTHER_TREE)], "scope_none": set(), "licensed": True,
                  "head": "", "reason": "other_tree"}, id="trust-a-verdict-about-another-tree-stops-the-walk"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _GREEN), _commit("2", _RED), _commit("3", _GREEN)], "scope_none": set(),
                  "licensed": True, "head": "1" * 40, "reason": "red"}, id="trust-nothing-ships-over-an-open-red"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("2", _RED), _commit("3", _GREEN, reverts="2" * 40)], "scope_none": set(),
                  "licensed": True, "head": "3" * 40, "reason": "all"}, id="trust-a-red-its-covered-revert-closes"),
    pytest.param(_the_trust_walk_ships_only_up_to_the_last_commit_every_verdict_covers,
                 {"commits": [_commit("1", _GREEN_FULL), _commit("2", _GREEN)], "scope_none": set(),
                  "licensed": False, "head": "1" * 40, "reason": "unlicensed"}, id="trust-unlicensed-only-a-full-green"),
    pytest.param(_the_baked_sum_moves_with_what_the_image_runs_and_not_with_its_tests_or_notes, {},
                 id="cycle-image-baked-sum"),
    pytest.param(_the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new,
                 {"state": {"good": "img", "good_sum": "s0"}, "word": "build"}, id="cycle-image-new-sum-builds"),
    pytest.param(_the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new,
                 {"state": {"good": "img", "good_sum": "s1"}, "word": "current"}, id="cycle-image-same-sum-is-current"),
    pytest.param(_the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new,
                 {"state": {"good": "img", "candidate": "new"}, "word": "trial"}, id="cycle-image-nothing-during-a-trial"),
    pytest.param(_the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new,
                 {"state": {"refused_sum": "s1", "refused_at": "900"}, "word": "refused"},
                 id="cycle-image-a-refused-sum-waits"),
    pytest.param(_the_cycle_builds_its_image_only_when_nothing_is_on_trial_and_the_sum_is_new,
                 {"state": {"refused_sum": "s1", "refused_at": "100"}, "word": "build"},
                 id="cycle-image-a-refused-sum-is-retried-later"),
    pytest.param(_the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long,
                 {"state": _TRIAL, "cycle_image": _NEW_IMAGE, "now": 1100.0, "action": "promote",
                  "jobs": [_cycle_job(_NEW_IMAGE, "1970-01-01T00:16:50Z", "Complete")]}, id="guard-one-green-cycle-promotes"),
    pytest.param(_the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long,
                 {"state": _TRIAL, "cycle_image": _NEW_IMAGE, "now": 1100.0, "action": "roll-back",
                  "jobs": [_cycle_job(_NEW_IMAGE, "1970-01-01T00:16:50Z", "Failed"),
                           _cycle_job(_NEW_IMAGE, "1970-01-01T00:17:00Z", "Failed")]}, id="guard-two-failed-cycles-roll-back"),
    pytest.param(_the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long,
                 {"state": _TRIAL, "cycle_image": _NEW_IMAGE, "now": 1100.0, "action": "wait",
                  "jobs": [_cycle_job(_NEW_IMAGE, "1970-01-01T00:16:00Z", "Complete"),
                           _cycle_job(_OLD_IMAGE, "1970-01-01T00:17:00Z", "Complete")]},
                 id="guard-a-green-before-the-trial-or-in-the-old-image-does-not-count"),
    pytest.param(_the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long,
                 {"state": _TRIAL, "cycle_image": _NEW_IMAGE, "now": 3000.0, "action": "roll-back", "jobs": []},
                 id="guard-no-green-cycle-in-time-rolls-back"),
    pytest.param(_the_guard_promotes_after_one_green_cycle_and_rolls_back_after_two_failed_or_too_long,
                 {"state": {}, "cycle_image": _OLD_IMAGE, "now": 1.0, "action": "seed", "jobs": []},
                 id="guard-seeds-the-image-in-use-as-good"),
    pytest.param(_a_promotion_moves_every_loop_object_and_its_image_setting_but_nothing_else, {},
                 id="cycle-image-pin-patches"),
]


@pytest.mark.parametrize("scenario, given", CASES)
def test_the_deploy_loop_asks_the_cluster_only_what_the_cycle_may_act_a_signed_push_to_main_starts_each_idle_loop_cronjob_a_gate_job_runs_the_gated_commit_in_its_own_pinned_image_on_a_clone_of_its_and_a_job_fault_never_reads_as_a_test_verdict(scenario, given, tmp_path: Path) -> None:
    """Every row of CASES must hold."""
    scenario(**given, tmp_path=tmp_path)

"""The deploy loop asks the cluster only what the cycle may act on: a signed push to main starts each idle loop CronJob once, a gate Job runs the gated commit in its own pinned image on a clone of its own, and a Job fault never reads as a test verdict.

WHAT IT PINS. `infra/deploy_loop` through its public names (`__all__`):
`push_should_trigger` and `cronjobs_to_start` (the receiver),
`gate_job_manifest` and `pinned_gate_image` (the Job), `gate_job_outcome`
(the Job read as an exit code), `bookmark_sha`, `image_targets` and
`stack_images`.

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
from pathlib import Path

import pytest

from infra.deploy_loop import (
    bookmark_sha,
    cronjobs_to_start,
    gate_job_manifest,
    gate_job_outcome,
    image_targets,
    pinned_gate_image,
    push_should_trigger,
    stack_images,
)

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


CASES = [
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
]


@pytest.mark.parametrize("scenario, given", CASES)
def test_the_deploy_loop_asks_the_cluster_only_what_the_cycle_may_act_a_signed_push_to_main_starts_each_idle_loop_cronjob_a_gate_job_runs_the_gated_commit_in_its_own_pinned_image_on_a_clone_of_its_and_a_job_fault_never_reads_as_a_test_verdict(scenario, given, tmp_path: Path) -> None:
    """Every row of CASES must hold."""
    scenario(**given, tmp_path=tmp_path)

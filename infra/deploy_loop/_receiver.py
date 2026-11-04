"""The push receiver: GitHub's webhook in, the deploy cycle and the lane started at once.

OWNS: the two checks every delivery must pass (`push_should_trigger`), which
CronJobs a push starts (`cronjobs_to_start`), and the small HTTP server the
`deploy-webhook` Deployment runs behind Caddy (`serve`).

THE TWO CHECKS: the HMAC-SHA256 signature over the raw body against
DEPLOY_WEBHOOK_SECRET, and `ref == refs/heads/main`. Every doubt is a no, and
an empty secret refuses everything: a receiver that trusts any caller lets
anyone on the internet start deploy cycles.

WHAT A PUSH STARTS. Every CronJob named in DEPLOY_RECEIVER_CRONJOBS (default
`deploy-cycle,commit-gate`: the cycle and the verifying lane), each as a Job
from its CronJob, each only when that CronJob exists, is not suspended, and has
no Job still active. A CronJob's `concurrencyPolicy: Forbid` covers only the
Jobs its own schedule starts, so this check is what keeps a push from running a
second cycle beside the first; the running one, or the next tick, takes the
commit.

FAILURE POLICY: a kubectl failure answers 500 and logs; GitHub shows the
delivery as failed and the CronJob's schedule still picks the commit up.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("deploy-webhook")


def push_should_trigger(secret: str, signature: str, body: bytes) -> tuple[bool, str]:
    """(start?, why) for one delivery's X-Hub-Signature-256 header and raw body."""
    if not secret:
        return False, "no webhook secret configured"
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        return False, "signature does not match"
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return False, "body is not JSON"
    if not isinstance(payload, dict) or payload.get("ref") != "refs/heads/main":
        return False, "not a push to main"
    return True, "push to main"


def cronjobs_to_start(wanted: list, cronjobs: dict, jobs: dict) -> list:
    """The names in `wanted` to start now, given `kubectl get cronjobs,jobs -o json` answers.

    A name is started when its CronJob exists, is not suspended, and owns no Job
    with an active pod. Jobs are matched to their CronJob by owner reference,
    and by the label `app.kubernetes.io/name` for a Job a push started.
    """
    present = {}
    for item in cronjobs.get("items") or []:
        name = (item.get("metadata") or {}).get("name", "")
        present[name] = bool((item.get("spec") or {}).get("suspend"))
    busy = set()
    for job in jobs.get("items") or []:
        if not ((job.get("status") or {}).get("active") or 0):
            continue
        metadata = job.get("metadata") or {}
        for owner in metadata.get("ownerReferences") or []:
            if owner.get("kind") == "CronJob":
                busy.add(owner.get("name", ""))
        busy.add((metadata.get("labels") or {}).get("app.kubernetes.io/name", ""))
    return [name for name in wanted if name in present and not present[name] and name not in busy]


def _kubectl(namespace: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "-n", namespace, *args], capture_output=True, text=True,
                          timeout=30, check=False)


def _get(namespace: str, kind: str) -> dict:
    answer = _kubectl(namespace, "get", kind, "-o", "json")
    if answer.returncode != 0:
        raise RuntimeError(answer.stderr.strip() or f"kubectl get {kind} failed")
    return json.loads(answer.stdout)


def _start(namespace: str, cronjob: str, sha: str) -> str:
    name = f"{cronjob}-push-{sha[:8] or 'nosha'}-{int(time.time())}"[:63]
    answer = _kubectl(namespace, "create", "job", f"--from=cronjob/{cronjob}", name)
    if answer.returncode != 0:
        raise RuntimeError(answer.stderr.strip() or "kubectl create job failed")
    return name


def start_for_push(namespace: str, wanted: list, sha: str) -> list:
    """Start every wanted CronJob that may start now; the names of the Jobs started."""
    names = cronjobs_to_start(wanted, _get(namespace, "cronjobs"), _get(namespace, "jobs"))
    return [_start(namespace, cronjob, sha) for cronjob in names]


def serve(port: int, secret: str, namespace: str, wanted: list) -> None:
    """Answer GitHub deliveries on `port` until the process is stopped."""

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code: int, text: str) -> None:
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server's spelling)
            healthy = self.path == "/healthz"
            self._answer(200 if healthy else 404, "ok" if healthy else "")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            start, why = push_should_trigger(secret, self.headers.get("X-Hub-Signature-256", ""), body)
            if not start:
                log.info("delivery refused: %s", why)
                self._answer(403 if why == "signature does not match" else 202, why)
                return
            sha = str((json.loads(body).get("head_commit") or {}).get("id") or "")
            try:
                started = start_for_push(namespace, wanted, sha)
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                log.error("push %s: could not start: %s", sha[:12], error)
                self._answer(500, "could not start the deploy loop")
                return
            log.info("push %s: started %s", sha[:12], ", ".join(started) or "nothing (already running)")
            self._answer(200, "started " + (", ".join(started) or "nothing; already running"))

        def log_message(self, fmt: str, *args) -> None:
            log.debug(fmt, *args)

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

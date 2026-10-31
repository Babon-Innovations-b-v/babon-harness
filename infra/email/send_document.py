"""Send an email, optionally with a PDF attached, through Scaleway's email API.

Scaleway blocks normal outgoing mail (SMTP) at the network level, so the
harness sends mail by POSTing to the Transactional Email (TEM) HTTPS API
instead. This script is standalone: Python 3, standard library only.

Settings, read from the process environment first and from the harness env
file second:

- TEM_PROJECT_ID   the Scaleway project that owns the verified sending domain
- TEM_FROM         the sender address, like noreply@your-domain.example
- TEM_REGION       Scaleway region; falls back to SCW_REGION, then fr-par

The env file is HARNESS_ENV_FILE when set, else config/harness.env in this
repository (the laptop), else $HARNESS_ROOT/harness.env (the server's pulled
vault cache, HARNESS_ROOT defaulting to /opt/harness). None of these has a
default project: with TEM_PROJECT_ID or TEM_FROM unset the script stops.

The sending credential is the Scaleway secret key. It comes from
SCW_SECRET_KEY in the process environment or from the scw CLI config
(`scw config get secret-key`), never from a file in the repository.

Sending needs a real domain registered with `scw tem domain create` and its
DNS records (SPF, DKIM, MX) verified by Scaleway. Free sslip.io names can
never send. Show the owner the exact document and get an explicit yes before
every send.

Usage:
    python3 infra/email/send_document.py \
        --to client@example.com \
        --subject "Invoice 2026-014" \
        --body "Dear client, please find the invoice attached." \
        --attach out/invoice-2026-014.pdf
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LAPTOP_ENV = _REPO_ROOT / "config" / "harness.env"
_DEFAULT_HARNESS_ROOT = "/opt/harness"
_TIMEOUT_S = 30


def _harness_env_path() -> Path:
    """The env file to read: HARNESS_ENV_FILE, the laptop file, else the server cache."""
    override = os.environ.get("HARNESS_ENV_FILE")
    if override:
        return Path(override)
    if _LAPTOP_ENV.exists():
        return _LAPTOP_ENV
    harness_root = os.environ.get("HARNESS_ROOT") or _DEFAULT_HARNESS_ROOT
    return Path(harness_root) / "harness.env"


def _load_harness_env() -> dict[str, str]:
    """Read the env file into a dict; a missing or unreadable file means an empty dict."""
    values: dict[str, str] = {}
    try:
        text = _harness_env_path().read_text()
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _resolve_setting(name: str, harness_env: dict[str, str], default: str = "") -> str:
    """One setting: environment wins, the harness env file second, default last."""
    return os.environ.get(name) or harness_env.get(name, "") or default


def _resolve_secret_key() -> str:
    """The Scaleway secret key: SCW_SECRET_KEY in the environment, else the scw CLI config."""
    from_environment = os.environ.get("SCW_SECRET_KEY", "")
    if from_environment:
        return from_environment
    try:
        result = subprocess.run(
            ["scw", "config", "get", "secret-key"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _read_body(args: argparse.Namespace) -> str:
    """The message text, from --body or from the file behind --body-file."""
    if args.body is not None:
        return args.body
    body_path = Path(args.body_file)
    if not body_path.exists():
        sys.exit(f"Body file not found: {body_path}")
    return body_path.read_text()


def _build_attachment(pdf_path: str) -> dict:
    """The TEM attachment object: file name, MIME type, base64 content."""
    path = Path(pdf_path)
    if not path.exists():
        sys.exit(f"Attachment not found: {path}")
    return {
        "name": path.name,
        "type": "application/pdf",
        "content": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _build_payload(args: argparse.Namespace, sender: str, project_id: str) -> dict:
    """The JSON body for the TEM /emails endpoint."""
    payload = {
        "from": {"email": sender},
        "to": [{"email": args.to}],
        "subject": args.subject,
        "text": _read_body(args),
        "project_id": project_id,
    }
    if args.attach:
        payload["attachments"] = [_build_attachment(args.attach)]
    return payload


def _explain_http_error(status: int, detail: str) -> str:
    """Turn a TEM API error into a plain-words explanation."""
    lowered = detail.lower()
    if "domain" in lowered and ("not" in lowered or "verif" in lowered or "check" in lowered):
        return (
            f"The API refused the send (HTTP {status}): the sending domain is not "
            "verified yet.\n"
            "Sending needs a real domain with its email DNS records added and "
            "checked by Scaleway; that check can take a while after the records "
            "are added. Free sslip.io names can never send.\n"
            f"API detail: {detail}"
        )
    if status in (401, 403):
        return (
            f"The API refused the credentials (HTTP {status}). Check that "
            "the Scaleway secret key belongs to the account that owns the "
            f"TEM domain, and that TEM_PROJECT_ID is the right project.\n"
            f"API detail: {detail}"
        )
    return f"The email API returned HTTP {status}.\nAPI detail: {detail}"


def _post(payload: dict, secret_key: str, region: str) -> dict:
    """POST the email to the TEM API; exit with a plain error on failure."""
    endpoint = (
        "https://api.scaleway.com/transactional-email/v1alpha1"
        f"/regions/{region}/emails"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-Auth-Token": secret_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(_explain_http_error(exc.code, detail))
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach the Scaleway email API: {exc.reason}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an email with an optional PDF attachment via Scaleway TEM."
    )
    parser.add_argument("--to", required=True, help="recipient email address")
    parser.add_argument("--subject", required=True, help="email subject line")
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", help="message text, given inline")
    body_group.add_argument("--body-file", help="path to a text file with the message")
    parser.add_argument("--attach", help="path to a PDF to attach")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    harness_env = _load_harness_env()

    secret_key = _resolve_secret_key()
    if not secret_key:
        sys.exit(
            "No Scaleway secret key: SCW_SECRET_KEY is not set and the scw CLI "
            "has none configured (scw init)."
        )
    project_id = _resolve_setting("TEM_PROJECT_ID", harness_env)
    sender = _resolve_setting("TEM_FROM", harness_env)
    if not project_id or not sender:
        sys.exit(
            "TEM_PROJECT_ID and TEM_FROM must be set, in the environment or in "
            f"{_harness_env_path()}. They are filled in when email sending is "
            "first set up (make-document skill)."
        )
    region = _resolve_setting(
        "TEM_REGION", harness_env,
        default=_resolve_setting("SCW_REGION", harness_env, default="fr-par"),
    )

    result = _post(_build_payload(args, sender, project_id), secret_key, region)
    email_ids = [email.get("id", "?") for email in result.get("emails", [])]
    print(f"Accepted by the email API. Message id: {', '.join(email_ids) or 'unknown'}")


if __name__ == "__main__":
    main()

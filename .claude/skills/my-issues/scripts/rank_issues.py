#!/usr/bin/env python3
"""Fetch the caller's own open GitHub issues and score them fastest-to-finish first.

Prints one JSON object to stdout: {"actionable": [...], "blocked": [...]}.
Scoring is mechanical (labels + checklist counts); the agent turns each row
into a plain-language explanation, that part is not scriptable.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[4] / ".claude" / "project.json"
REPO = json.loads(CONFIG_PATH.read_text())["repo"]
BLOCKED_STATES = {"needs-triage", "needs-info"}
STATE_ROLES = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}


def fetch_issues():
    result = subprocess.run(
        [
            "gh", "issue", "list", "--repo", REPO,
            "--assignee", "@me", "--state", "open",
            "--json", "number,title,body,url,labels",
            "--limit", "200",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gh issue list failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def score(body, labels):
    unchecked = len(re.findall(r"^- \[ \]", body, re.MULTILINE))
    questions = len(re.findall(r"^\s*-\s.*\?\s*$", body, re.MULTILINE))
    is_prd = "PRD" in labels
    ready_for_human_penalty = 1 if "ready-for-human" in labels else 0
    return unchecked * 2 + questions * 3 + (10 if is_prd else 0) + ready_for_human_penalty


def main():
    actionable, blocked = [], []
    for issue in fetch_issues():
        labels = [l["name"] for l in issue["labels"]]
        if "wontfix" in labels:
            continue
        body = issue.get("body") or ""
        row = {
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "labels": labels,
            "body": body,
        }
        state_role = next((l for l in labels if l in STATE_ROLES), None)
        if state_role in BLOCKED_STATES:
            row["blocked_reason"] = state_role
            blocked.append(row)
        else:
            row["score"] = score(body, labels)
            actionable.append(row)

    actionable.sort(key=lambda r: r["score"])
    print(json.dumps({"actionable": actionable, "blocked": blocked}, indent=2))


if __name__ == "__main__":
    main()

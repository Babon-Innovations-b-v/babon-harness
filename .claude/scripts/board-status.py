#!/usr/bin/env python3
"""Set the Status column of an issue on the project board.

    python3 .claude/scripts/board-status.py <issue-number> <status>

Status is one of the board columns created by setup-github.py: "LowPriority",
"Not started", "In Progress", "Review", "Done". Repo and board number come from
.claude/project.json; nothing is hard-coded. Needs an authenticated `gh`.

An issue that is not on the board yet is added first, so this works whether or not the
board's auto-add workflow is switched on.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

CONFIG_PATH = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "project.json"


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{' '.join(args[:3])} failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def graphql(query: str, **variables) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-F", f"{key}={value}"]
    payload = json.loads(run(args) or "{}")
    if "errors" in payload:
        sys.exit(f"GraphQL failed: {json.dumps(payload['errors'])}")
    return payload["data"]


def checkout_repo() -> str:
    """owner/name for this checkout's origin remote, or "" when there is none."""
    result = subprocess.run(["git", "-C", str(CONFIG_PATH.parents[1]), "remote", "get-url", "origin"],
                            capture_output=True, text=True)
    url = result.stdout.strip().removesuffix(".git")
    if result.returncode != 0 or not url:
        return ""
    # git@host:owner/name and https://host/owner/name both end in owner/name once ":" is a "/".
    return "/".join(url.replace(":", "/").split("/")[-2:])


def config() -> tuple[str, str, int, str]:
    """Return (owner, name, project number, project owner) from .claude/project.json."""
    if not CONFIG_PATH.exists():
        sys.exit("no .claude/project.json. Run: python3 .claude/scripts/setup-github.py --board")
    data = json.loads(CONFIG_PATH.read_text())
    repo = data.get("repo") or ""
    here = checkout_repo()
    if here and repo and here != repo:
        # A config copied from the template still names the template's repo and board.
        # Setting a column there would move a card on somebody else's board.
        sys.exit(
            f"project.json names {repo} but this checkout is {here}. "
            "Run: python3 .claude/scripts/setup-github.py --board"
        )
    project = data.get("project") or {}
    if "/" not in repo or not project.get("number"):
        sys.exit("project.json has no repo or board number. Run setup-github.py --board first.")
    owner, name = repo.split("/", 1)
    return owner, name, int(project["number"]), project.get("owner") or owner


def status_field(number: int, project_owner: str) -> dict:
    """The Status single-select field, with its options."""
    listing = run(["gh", "project", "field-list", str(number), "--owner", project_owner, "--format", "json"])
    field = next((f for f in json.loads(listing or "{}").get("fields", []) if f["name"] == "Status"), None)
    if field is None:
        sys.exit(f"project #{number} has no Status field")
    return field


def board_item(owner: str, name: str, issue: int, number: int) -> tuple[str, str] | None:
    """(item id, project id) for this issue on this board, or None when it is not on it."""
    data = graphql(
        """query($o:String!,$n:String!,$i:Int!){
             repository(owner:$o,name:$n){ issue(number:$i){
               id projectItems(first:20){ nodes{ id project{ id number } } } } }
           }""",
        o=owner, n=name, i=str(issue),
    )
    issue_node = data["repository"]["issue"]
    if issue_node is None:
        sys.exit(f"#{issue} does not exist in {owner}/{name}")
    for node in issue_node["projectItems"]["nodes"]:
        if node["project"]["number"] == number:
            return node["id"], node["project"]["id"]
    return None


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    issue = int(sys.argv[1])
    wanted = sys.argv[2]

    owner, name, number, project_owner = config()
    field = status_field(number, project_owner)
    options = field.get("options", [])
    option = next((o for o in options if o["name"] == wanted), None)
    if option is None:
        sys.exit(f"unknown status {wanted!r}; board columns: {', '.join(o['name'] for o in options)}")

    found = board_item(owner, name, issue, number)
    if found is None:
        run(["gh", "project", "item-add", str(number), "--owner", project_owner,
             "--url", f"https://github.com/{owner}/{name}/issues/{issue}"])
        found = board_item(owner, name, issue, number)
        if found is None:
            sys.exit(f"#{issue} could not be added to board #{number}")
        print(f"#{issue} added to board #{number}")
    item_id, project_id = found

    graphql(
        """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
             updateProjectV2ItemFieldValue(input:{
               projectId:$p, itemId:$i, fieldId:$f, value:{singleSelectOptionId:$o}
             }){ projectV2Item{ id } }
           }""",
        p=project_id, i=item_id, f=field["id"], o=option["id"],
    )
    print(f"#{issue} -> {wanted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

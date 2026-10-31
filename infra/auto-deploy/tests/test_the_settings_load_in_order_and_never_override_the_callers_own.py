"""Settings load committed file first, vault cache second, caller's environment wins.

WHAT IT PINS. `harness_load_config` in `steps/doors.sh`, which every deploy
script uses to read config/harness.env and the vault cache.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Two files are
written by hand, each setting keys the other also sets, and one key is set in
the caller's environment too. Which value must win follows from the documented
order, written here, never from an earlier run. The loader must also never
EXECUTE a file: a value that would run a command if sourced stays text.

WHAT IT WAS PROVED AGAINST. Letting a file override a key already in the
environment, which is how a hand run's override would silently not apply.

GUARDS. The three-place configuration contract.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_DOORS = Path(__file__).resolve().parents[1] / "steps" / "doors.sh"


def test_the_vault_wins_over_the_settings_and_the_caller_wins_over_both(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/harness.env").write_text(
        "# settings\nDOMAIN=example.org\nEJECT_ENABLED=0\nSHARED=from-settings\n"
        "export QUOTED='a b'\nTRAP=$(touch " + str(tmp_path / "ran") + ")\n",
        encoding="utf-8",
    )
    vault = tmp_path / "harness.env"
    vault.write_text('SHARED="from-vault"\nEJECT_ENABLED=1\n', encoding="utf-8")
    script = "\n".join((
        f'. "{_DOORS}"',
        f'HARNESS_ENV_FILE="{vault}" harness_load_config "{repo}"',
        'printf "%s|%s|%s|%s|%s\\n" "$DOMAIN" "$SHARED" "$EJECT_ENABLED" "$QUOTED" "$TRAP"',
    ))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "EJECT_ENABLED": "caller"},
    )
    assert done.stdout.strip() == "example.org|from-vault|caller|a b|$(touch " + str(tmp_path / "ran") + ")"
    assert not (tmp_path / "ran").exists(), "the loader executed a value"

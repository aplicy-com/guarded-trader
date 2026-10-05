"""scripts/drill-check.sh: an unreadable ledger must read as halts=unknown, never halts=0."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "drill-check.sh"

# A fake `docker` driven by env vars, so no daemon is needed.
#   CONDUCTOR_UP=1      the conductor container "runs"; `docker exec ... conductor.cli` uses CLI_*
#   LEDGER_PRESENT=1    image + volume exist for the stopped-conductor ledger peek
FAKE_DOCKER = r"""#!/usr/bin/env bash
case "$1" in
  inspect)  # docker inspect -f '{{.State.Running}}' NAME
    case "$4" in
      *conductor) [ "${CONDUCTOR_UP:-0}" = 1 ] && echo true || echo false ;;
      *) echo false ;;
    esac ;;
  image|volume) [ "${LEDGER_PRESENT:-0}" = 1 ] ;;
  exec)  # only the halts CLI matters here
    if [[ "$*" == *conductor.cli* ]]; then echo "${CLI_OUT:-}"; exit "${CLI_RC:-0}"; fi
    exit 1 ;;
  run)   echo "${RUN_OUT:-}"; exit "${RUN_RC:-0}" ;;
  *) exit 0 ;;
esac
"""


@pytest.fixture
def fake_path(tmp_path: Path) -> str:
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return f"{tmp_path}:{os.environ['PATH']}"


def brief(path: str, **env: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--brief"],  # noqa: S607
        env={**os.environ, "PATH": path, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return out.stdout


def test_missing_ledger_reports_unknown_not_zero(fake_path: str) -> None:
    assert " halts=unknown " in brief(fake_path)


def test_conductor_stopped_and_ledger_read_fails_reports_unknown(fake_path: str) -> None:
    out = brief(fake_path, LEDGER_PRESENT="1", RUN_RC="1", RUN_OUT="boom")
    assert " halts=unknown " in out


def test_cli_failure_while_conductor_runs_reports_unknown(fake_path: str) -> None:
    out = brief(fake_path, CONDUCTOR_UP="1", CLI_RC="1", CLI_OUT="Traceback: no such table")
    assert " halts=unknown " in out


def test_readable_ledger_still_counts_halts(fake_path: str) -> None:
    line = "#1 kill_switch [all instances] ACTIVE :: by hand"
    assert " halts=1 " in brief(fake_path, CONDUCTOR_UP="1", CLI_OUT=line)
    assert " halts=0 " in brief(fake_path, CONDUCTOR_UP="1", CLI_OUT="no active halts")


def test_expectation_fails_when_halts_unknown(fake_path: str) -> None:
    res = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--expect-halts", "0"],  # noqa: S607
        env={**os.environ, "PATH": fake_path},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert res.returncode == 1
    assert "CHECK FAIL" in res.stdout

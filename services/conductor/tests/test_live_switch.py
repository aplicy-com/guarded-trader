"""scripts/trading-mode.sh and scripts/compose.sh: the dry_run <-> live switch and its gates.

A fake `docker` driven by files in a scratch directory stands in for the daemon, so every gate
can be forced to pass or fail and the exact docker calls (and their order) can be asserted.
"""

import io
import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

FAKE_DOCKER = r"""#!/usr/bin/env bash
F="$FAKE_DIR"
echo "$*" >> "$F/calls.log"
args="$*"
case "$1" in
  inspect)
    case "$args" in
      *State.Running*)       [ -e "$F/running/${@: -1}" ] && echo true || echo false ;;
      *Health.Status*)       echo healthy ;;
    esac ;;
  volume)  [ -e "$F/volumes/${@: -1}" ] ;;
  exec)
    if [[ "$args" == *soak-check* ]]; then cat "$F/soak.out"; exit "$(cat "$F/soak.rc")"; fi
    if [[ "$args" == *"python -"* ]]; then cat "$F/ft_self"; fi ;;
  run)
    if [[ "$args" == *"--entrypoint tar"* ]]; then
      [ -e "$F/tar_fail" ] && exit 1
      cat "$F/ledger.tgz"; exit 0
    fi
    if [[ "$args" == *"--entrypoint python"* ]]; then cat "$F/ledger_probe"; exit 0; fi ;;
  compose)
    if [[ "$args" == *" run "* ]]; then cat "$F/r5.out"; exit "$(cat "$F/r5.rc")"; fi ;;
esac
exit 0
"""

FAKE_KEY_CHECK = '#!/usr/bin/env bash\necho "key check ran: $*"\nexit "$(cat "$FAKE_DIR/key.rc")"\n'


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root / "app"
        self.fake = root / "fake"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "infra" / "live").mkdir(parents=True)
        (self.root / "services/freqtrade/user_data").mkdir(parents=True)
        (self.fake / "running").mkdir(parents=True)
        (self.fake / "volumes").mkdir()
        (self.fake / "bin").mkdir()
        for name in ("trading-mode.sh", "compose.sh"):
            shutil.copy(REPO / "scripts" / name, self.root / "scripts" / name)
        (self.root / ".env").write_text("")
        (self.root / "infra/live/soak-start").write_text("2026-10-05T15:29:00Z\n")
        (self.root / "services/freqtrade/user_data/tradesv3.dryrun.sqlite").write_text("x")
        docker = self.fake / "bin" / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
        key = self.fake / "kraken-check.sh"
        key.write_text(FAKE_KEY_CHECK)
        key.chmod(key.stat().st_mode | stat.S_IXUSR)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("./conductor.db")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        (self.fake / "ledger.tgz").write_bytes(buf.getvalue())
        # defaults: everything passes, dry-run stack up
        self.set("soak.out", "SOAK MET")
        self.set("soak.rc", "0")
        self.set("key.rc", "0")
        self.set("ledger_probe", "principal=NONE trades=0")
        self.set("ft_self", "dry_run=False state=paused positions=0 orders=0")
        self.set("r5.out", "R5 CHECK PASS")
        self.set("r5.rc", "0")
        self.running("ai-trading-agent-conductor")

    def set(self, name: str, text: str) -> None:
        (self.fake / name).write_text(text + "\n")

    def running(self, name: str) -> None:
        (self.fake / "running" / name).write_text("")

    def volume(self, name: str) -> None:
        (self.fake / "volumes" / name).write_text("")

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.fake / 'bin'}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.fake),
            "KRAKEN_ACCESS_CHECK": str(self.fake / "kraken-check.sh"),
        }
        return subprocess.run(  # noqa: S603
            ["bash", str(self.root / "scripts" / "trading-mode.sh"), *args],  # noqa: S607
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def calls(self) -> list[str]:
        path = self.fake / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def mode(self) -> str | None:
        f = self.root / ".trading-mode"
        return f.read_text().strip() if f.exists() else None

    def changed_anything(self) -> bool:
        return any(c.startswith("compose") and (" down" in c or " up " in c) for c in self.calls())


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def idx(calls: list[str], needle: str) -> int:
    return next(i for i, c in enumerate(calls) if needle in c)


# ---- going live -----------------------------------------------------------------------------


def test_everything_passes_goes_live_in_the_right_order(sb: Sandbox) -> None:
    res = sb.run("live")
    assert res.returncode == 0, res.stdout + res.stderr
    assert sb.mode() == "live"
    calls = sb.calls()
    # gates first, then stop dry-run, archive, live freqtrade, R5, then the live conductor
    order = [
        idx(calls, "soak-check"),
        idx(calls, "volume inspect"),
        idx(calls, "docker-compose.yml down")
        if any("docker-compose.yml down" in c for c in calls)
        else idx(calls, " down"),
        idx(calls, "--entrypoint tar"),
        idx(calls, "up -d --no-deps --build freqtrade"),
        idx(calls, "isolation-check"),
        idx(calls, "up -d --no-deps conductor"),
    ]
    assert order == sorted(order) and len(set(order)) == len(order)
    live_calls = [c for c in calls if "up -d --no-deps" in c]
    assert all("docker-compose.live.yml" in c for c in live_calls)  # live override, never dry-run
    archives = list((sb.root / "archive").glob("dry-run-*.tgz"))
    assert len(archives) == 2
    assert all(stat.S_IMODE(a.stat().st_mode) == 0o600 for a in archives)
    assert "LIVE" in res.stdout


def test_soak_not_met_changes_nothing(sb: Sandbox) -> None:
    sb.set("soak.out", "SOAK NOT MET: not enough time has passed")
    sb.set("soak.rc", "1")
    res = sb.run("live")
    assert res.returncode == 1 and "FAIL soak" in res.stdout
    assert sb.mode() is None and not sb.changed_anything()
    assert not (sb.root / "archive").exists()


def test_soak_needs_the_dry_run_conductor_running(sb: Sandbox) -> None:
    (sb.fake / "running" / "ai-trading-agent-conductor").unlink()
    res = sb.run("live")
    assert res.returncode == 1 and "not running" in res.stdout
    assert not sb.changed_anything()


def test_bad_key_scopes_change_nothing(sb: Sandbox) -> None:
    sb.set("key.rc", "1")
    res = sb.run("live")
    assert res.returncode == 1 and "FAIL key scopes" in res.stdout
    assert "--scope trade" in res.stdout  # the real (trade) scope is what gets verified
    assert not sb.changed_anything() and sb.mode() is None


def test_a_dry_run_ledger_in_the_live_volume_is_refused(sb: Sandbox) -> None:
    sb.volume("infra_conductor-data-live")
    sb.set("ledger_probe", "principal=100 trades=1")
    res = sb.run("live")
    assert res.returncode == 1 and "FAIL ledger" in res.stdout
    assert not sb.changed_anything()


@pytest.mark.parametrize("probe", ["principal=NONE trades=0", "principal=20 trades=3"])
def test_an_empty_or_own_live_ledger_is_fine(sb: Sandbox, probe: str) -> None:
    sb.volume("infra_conductor-data-live")
    sb.set("ledger_probe", probe)
    assert sb.run("live").returncode == 0


def test_a_failed_archive_restarts_dry_run_and_goes_nowhere(sb: Sandbox) -> None:
    (sb.fake / "tar_fail").write_text("")
    res = sb.run("live")
    assert res.returncode == 1 and "archive failed" in res.stderr
    assert sb.mode() is None
    calls = sb.calls()
    assert idx(calls, " down") < idx(calls, "up -d")  # stopped, then put back
    assert not any("docker-compose.live.yml" in c and " up " in c for c in calls)


def test_freqtrade_still_in_dry_run_stops_before_the_conductor(sb: Sandbox) -> None:
    sb.set("ft_self", "dry_run=True state=paused positions=0 orders=0")
    res = sb.run("live")
    assert res.returncode == 1 and "gate MODE" in res.stderr
    assert sb.mode() == "live-pending"
    assert not any("up -d --no-deps conductor" in c for c in sb.calls())


def test_freqtrade_not_paused_stops_before_the_conductor(sb: Sandbox) -> None:
    sb.set("ft_self", "dry_run=False state=running positions=0 orders=0")
    assert sb.run("live").returncode == 1
    assert not any("up -d --no-deps conductor" in c for c in sb.calls())


def test_r5_failure_leaves_live_pending_and_a_rerun_completes(sb: Sandbox) -> None:
    sb.set("r5.out", "R5 CHECK FAIL: unexplained LTC")
    sb.set("r5.rc", "1")
    res = sb.run("live")
    assert res.returncode == 1 and "R5 gate failed" in res.stderr
    assert sb.mode() == "live-pending"
    assert not any("up -d --no-deps conductor" in c for c in sb.calls())

    # operator records the exclusion; the dry-run conductor is down now, so the soak gate is
    # not re-asked, but key + ledger are, and R5 must now pass
    (sb.fake / "running" / "ai-trading-agent-conductor").unlink()
    sb.set("soak.rc", "1")  # would fail if it were asked again
    sb.set("r5.out", "R5 CHECK PASS")
    sb.set("r5.rc", "0")
    sb.volume("infra_conductor-data-live")
    sb.set("ledger_probe", "principal=NONE trades=0")
    res = sb.run("live")
    assert res.returncode == 0, res.stdout + res.stderr
    assert sb.mode() == "live"


def test_a_failed_key_check_on_the_rerun_still_blocks_live_pending(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("live-pending\n")
    sb.set("key.rc", "1")
    assert sb.run("live").returncode == 1
    assert sb.mode() == "live-pending"
    assert not any("up -d --no-deps conductor" in c for c in sb.calls())


def test_there_is_no_way_to_skip_a_gate_or_shorten_the_soak(sb: Sandbox) -> None:
    for extra in ("--force", "--skip-soak", "--hours", "1"):
        res = sb.run("live", extra)
        assert res.returncode == 2 and "gates cannot be skipped" in res.stderr
    assert not sb.changed_anything()


def test_already_live_is_a_noop(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("live\n")
    res = sb.run("live")
    assert res.returncode == 0 and "already live" in res.stdout
    assert not sb.changed_anything()


# ---- going back -----------------------------------------------------------------------------


def go_live_state(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("live\n")
    sb.running("ai-trading-agent-freqtrade")


def test_back_to_dry_run_when_flat(sb: Sandbox) -> None:
    go_live_state(sb)
    res = sb.run("dry-run")
    assert res.returncode == 0, res.stdout + res.stderr
    assert sb.mode() == "dry-run"
    calls = sb.calls()
    down = idx(calls, "docker-compose.live.yml down")
    up = next(
        i for i, c in enumerate(calls) if " up -d" in c and "docker-compose.live.yml" not in c
    )
    assert down < up
    assert not any(" -v" in c or "volume rm" in c for c in calls)  # the live ledger is kept


@pytest.mark.parametrize(
    "ft_self",
    [
        "dry_run=False state=paused positions=1 orders=0",
        "dry_run=False state=running positions=0 orders=1",
        "unreachable",
    ],
)
def test_back_to_dry_run_refused_while_real_exposure_is_open_or_unknown(
    sb: Sandbox, ft_self: str
) -> None:
    go_live_state(sb)
    sb.set("ft_self", ft_self)
    res = sb.run("dry-run")
    assert res.returncode == 1
    assert sb.mode() == "live" and not sb.changed_anything()


def test_back_to_dry_run_refused_when_freqtrade_is_down(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("live\n")  # freqtrade container not running
    assert sb.run("dry-run").returncode == 1
    assert sb.mode() == "live"


def test_live_pending_can_be_backed_out(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("live-pending\n")
    assert sb.run("dry-run").returncode == 0
    assert sb.mode() == "dry-run"


# ---- cli and status --------------------------------------------------------------------------


def test_cli_targets_the_live_ledger_only(sb: Sandbox) -> None:
    res = sb.run("cli", "capital")
    assert res.returncode == 1 and "dry-run" in res.stderr  # not in live: refuse
    (sb.root / ".trading-mode").write_text("live\n")
    sb.run("cli", "exclude-balance", "--asset", "ETH", "--operator", "m")
    assert any(
        "compose" in c and "docker-compose.live.yml" in c and " run " in c for c in sb.calls()
    ) or any(
        "exec ai-trading-agent-conductor python -m conductor.cli exclude-balance" in c
        for c in sb.calls()
    )


def test_status_reports_the_mode(sb: Sandbox) -> None:
    assert "mode: dry-run" in sb.run("status").stdout
    (sb.root / ".trading-mode").write_text("live\n")
    assert "mode: live" in sb.run("status").stdout


def test_a_garbage_mode_file_is_an_error(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("yolo\n")
    assert sb.run("status").returncode == 2


# ---- compose.sh ------------------------------------------------------------------------------


def compose(sb: Sandbox, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{sb.fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(sb.fake),
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(sb.root / "scripts" / "compose.sh"), *args],  # noqa: S607
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("mode", "live_file"),
    [(None, False), ("dry-run", False), ("live", True), ("live-pending", True)],
)
def test_compose_wrapper_picks_files_from_the_mode(
    sb: Sandbox, mode: str | None, live_file: bool
) -> None:
    if mode:
        (sb.root / ".trading-mode").write_text(f"{mode}\n")
    assert compose(sb, "up", "-d").returncode == 0
    call = sb.calls()[-1]
    assert ("docker-compose.live.yml" in call) is live_file
    assert "-f infra/docker-compose.yml" in call


def test_compose_wrapper_rejects_a_garbage_mode(sb: Sandbox) -> None:
    (sb.root / ".trading-mode").write_text("yolo\n")
    assert compose(sb, "up", "-d").returncode == 2

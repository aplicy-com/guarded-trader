"""scripts/restore-test.sh: the trading mode is mandatory and selects the B2 prefix (ADR-0019).

A fake `aws` serves objects from a scratch directory, so the prefix the script lists and the key
it downloads can be asserted exactly. Real sqlite3, gzip and bash do the rest.
"""

import gzip
import os
import sqlite3
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "restore-test.sh"

FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/aws.log"
if [[ "$*" == *list-objects-v2* ]]; then
  prefix=""
  while [ $# -gt 0 ]; do [ "$1" = --prefix ] && prefix=$2; shift; done
  # every fixture key under the prefix, newest last, as "Key<TAB>LastModified"
  grep -F "$prefix" "$FAKE_DIR/objects.txt" | while IFS= read -r key; do
    case "${key#"$prefix"}" in */*) continue ;; esac   # S3 prefixes are not recursive here
    printf '%s\t%s\n' "$key" "$STAMP"
  done
  exit 0
fi
if [ "$1" = s3 ] && [ "$2" = cp ] || [[ "$*" == *" s3 cp "* ]]; then
  src=""; dest=""
  for a in "$@"; do case "$a" in s3://*) src=${a#s3://*/} ;; *.gz) dest=$a ;; esac; done
  cp "$FAKE_DIR/store/$(echo "$src" | tr / _)" "$dest"
  exit 0
fi
exit 0
"""


class Bucket:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "bin").mkdir(parents=True)
        (root / "store").mkdir()
        aws = root / "bin" / "aws"
        aws.write_text(FAKE_AWS)
        aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
        (root / "objects.txt").write_text("")

    def put(self, key: str, principal: str) -> None:
        db = self.root / "tmp.sqlite"
        db.unlink(missing_ok=True)
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE principal (amount TEXT, currency TEXT)")
        conn.execute("INSERT INTO principal VALUES (?, 'USD')", (principal,))
        conn.execute("CREATE TABLE halts (id INTEGER, halt_type TEXT)")
        conn.execute("CREATE TABLE halt_clears (id INTEGER, halt_id INTEGER)")
        conn.execute("CREATE TABLE audit_log (id INTEGER, at TEXT, action TEXT)")
        conn.commit()
        conn.close()
        (self.root / "store" / key.replace("/", "_")).write_bytes(gzip.compress(db.read_bytes()))
        with (self.root / "objects.txt").open("a") as f:
            f.write(key + "\n")

    def run(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        full = {
            **os.environ,
            "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.root),
            "STAMP": datetime.now(UTC).isoformat(),
            "BACKUP_B2_BUCKET": "b",
            "BACKUP_B2_ENDPOINT": "https://s3.us-west-004.backblazeb2.com",
            "RESTORE_B2_KEY_ID": "id",
            "RESTORE_B2_APP_KEY": "secret",
            **(env or {}),
        }
        return subprocess.run(  # noqa: S603
            ["bash", str(SCRIPT), *args],  # noqa: S607
            env=full,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def listed_prefixes(self) -> list[str]:
        log = (
            (self.root / "aws.log").read_text().splitlines()
            if (self.root / "aws.log").exists()
            else []
        )
        return [line.split("--prefix ")[1].split()[0] for line in log if "--prefix" in line]


@pytest.fixture
def bucket(tmp_path: Path) -> Bucket:
    b = Bucket(tmp_path)
    b.put("backups/live/conductor/conductor-20261010T031500Z-aaaaaa.sqlite.gz", "20")
    b.put("backups/live/freqtrade/freqtrade-20261010T031500Z-aaaaaa.sqlite.gz", "20")
    b.put("backups/dry_run/conductor/conductor-20261010T031500Z-bbbbbb.sqlite.gz", "100")
    b.put("backups/dry_run/freqtrade/freqtrade-20261010T031500Z-bbbbbb.sqlite.gz", "100")
    b.put("backups/conductor/conductor-20261005T031500Z-cccccc.sqlite.gz", "100")  # pre-split
    b.put("backups/freqtrade/freqtrade-20261005T031500Z-cccccc.sqlite.gz", "100")
    return b


def test_mode_is_mandatory_and_nothing_is_contacted_without_it(bucket: Bucket) -> None:
    res = bucket.run("all")
    assert res.returncode == 1 and "--mode is required" in res.stderr
    assert bucket.listed_prefixes() == []


@pytest.mark.parametrize("bad", ["prod", "LIVE", "", "dry-run"])
def test_unknown_modes_are_rejected(bucket: Bucket, bad: str) -> None:
    res = bucket.run("--mode", bad, "all")
    assert res.returncode == 1 and "--mode" in res.stderr
    assert bucket.listed_prefixes() == []


def test_a_bare_mode_flag_is_an_error(bucket: Bucket) -> None:
    assert bucket.run("all", "--mode").returncode == 1


@pytest.mark.parametrize(
    ("mode", "root", "principal"),
    [("live", "backups/live", "20 USD"), ("dry_run", "backups/dry_run", "100 USD")],
)
def test_each_mode_reads_only_its_own_prefix(
    bucket: Bucket, mode: str, root: str, principal: str
) -> None:
    res = bucket.run("--mode", mode, "all")
    assert res.returncode == 0, res.stdout + res.stderr
    assert bucket.listed_prefixes() == [f"{root}/conductor/", f"{root}/freqtrade/"]
    assert f"latest : {root}/conductor/conductor-" in res.stdout
    assert f"principal: {principal}" in res.stdout  # the right ledger, not the other mode's
    assert f"(mode: {mode})" in res.stdout
    assert "RESTORE TEST PASSED" in res.stdout


def test_live_mode_never_returns_a_dry_run_backup_even_when_it_is_newer(bucket: Bucket) -> None:
    bucket.put("backups/dry_run/conductor/conductor-20261099T000000Z-zzzzzz.sqlite.gz", "100")
    res = bucket.run("--mode", "live", "conductor")
    assert (
        "principal: 20 USD" in res.stdout
        and "dry_run" not in res.stdout.split("latest")[1].split("\n")[0]
    )


def test_legacy_reads_the_pre_split_layout_only(bucket: Bucket) -> None:
    res = bucket.run("--mode", "legacy", "conductor")
    assert res.returncode == 0, res.stdout + res.stderr
    assert bucket.listed_prefixes() == ["backups/conductor/"]
    assert "latest : backups/conductor/conductor-20261005T031500Z-cccccc" in res.stdout


def test_an_empty_mode_fails_and_points_dry_run_users_at_legacy(tmp_path: Path) -> None:
    b = Bucket(tmp_path)
    b.put("backups/conductor/conductor-20261005T031500Z-cccccc.sqlite.gz", "100")
    res = b.run("--mode", "dry_run", "conductor")
    assert res.returncode == 1
    assert "no backups found under backups/dry_run/conductor/" in res.stdout
    assert "--mode legacy" in res.stdout
    live = b.run("--mode", "live", "conductor")
    assert live.returncode == 1 and "--mode legacy" not in live.stdout


def test_keep_and_single_source_still_work(bucket: Bucket, tmp_path: Path) -> None:
    keep = tmp_path / "kept"
    res = bucket.run("--mode", "live", "conductor", "--keep", str(keep))
    assert res.returncode == 0
    assert (keep / "conductor.sqlite").exists() and not (keep / "freqtrade.sqlite").exists()

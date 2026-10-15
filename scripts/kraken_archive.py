#!/usr/bin/env python3
"""Kraken's official OHLCVT bulk archive -> verified Freqtrade feather files (ADR-0020).

Kraken publishes a free, complete per-pair candle history (support article
360047124832): a full-history zip split into ~2 GB parts, plus quarterly
incremental zips. Each is a set of headerless CSVs named `<PAIR>_<minutes>.csv`
with columns `timestamp, open, high, low, close, volume, trades`. Timestamps are
Unix seconds at the candle *open*, the same convention Freqtrade uses: checked on
2026-10-14 against 720 daily candles from Kraken's REST OHLC endpoint, which
matched to the last digit. Intervals with no trades are omitted, not zero-filled.

Subcommands:

  download   Fetch the full-history parts and the incrementals named in
             kraken_archive_checksums.json into --archive-dir (resumes partial
             files). Needs network. Standard library only.
  verify     SHA-256 every part, the reassembled full zip (streamed, never
             written to disk) and every incremental against the pinned values.
             Standard library only. Exits non-zero on any mismatch.
  convert    Read the whitelisted pairs' 4h and 1d CSVs straight out of the
             verified zips (parts are read as one stream, never concatenated
             on disk), merge the incrementals, validate, and write Freqtrade
             feather files plus kraken-archive-report.json into --out. Needs
             pandas and Freqtrade: run it in the Freqtrade image with
             --network none (`make kraken-data` does).
  crossval   Compare Kraken closes with Binance closes already on disk (ADR-0020:
             Binance is a private cross-check only, never the promotion path).
             Read-only; writes nothing but the report it prints.

No data is ever committed to the repo; only the checksums file is.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKSUMS = Path(__file__).resolve().parent / "kraken_archive_checksums.json"
DRY_RUN_CONFIG = REPO_ROOT / "services" / "freqtrade" / "user_data" / "config.dry_run.json"
DATA_ROOT = REPO_ROOT / "services" / "freqtrade" / "user_data" / "data"
DEFAULT_ARCHIVE_DIR = DATA_ROOT / "kraken-archive"
DEFAULT_OUT_DIR = DATA_ROOT / "kraken"
REPORT_NAME = "kraken-archive-report.json"

# Freqtrade timeframe -> archive interval in minutes.
TIMEFRAMES = {"4h": 240, "1d": 1440}
# Kraken's legacy asset code for bitcoin; every other whitelisted base is unchanged.
KRAKEN_BASE = {"BTC": "XBT"}
CHUNK = 1 << 20


def load_checksums() -> dict:
    return json.loads(CHECKSUMS.read_text())


def load_pairs() -> list[str]:
    return json.loads(DRY_RUN_CONFIG.read_text())["exchange"]["pair_whitelist"]


def archive_symbol(pair: str) -> str:
    """`BTC/USD` -> `XBTUSD`, the file stem Kraken uses in the archive."""
    base, quote = pair.split("/")
    return f"{KRAKEN_BASE.get(base, base)}{quote}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class MultiPartReader(io.RawIOBase):
    """Read a list of files as one seekable stream (zip parts are a plain byte split)."""

    def __init__(self, paths: list[Path]) -> None:
        self._files = [p.open("rb") for p in paths]
        self._sizes = [p.stat().st_size for p in paths]
        self._total = sum(self._sizes)
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_SET:
            self._pos = offset
        elif whence == os.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self._total + offset
        return self._pos

    def readinto(self, buffer) -> int:  # type: ignore[override]
        want = len(buffer)
        written = 0
        local = self._pos
        for f, size in zip(self._files, self._sizes, strict=True):
            if local >= size:
                local -= size
                continue
            f.seek(local)
            chunk = f.read(min(want - written, size - local))
            buffer[written : written + len(chunk)] = chunk
            written += len(chunk)
            local = 0
            if written >= want:
                break
        self._pos += written
        return written

    def close(self) -> None:
        for f in self._files:
            f.close()
        super().close()


def part_paths(archive_dir: Path, sums: dict) -> list[Path]:
    return [archive_dir / name for name in sorted(sums["full_parts"])]


# --- download / verify (stdlib only) --------------------------------------------------------


def cmd_download(args: argparse.Namespace) -> int:
    sums = load_checksums()
    args.archive_dir.mkdir(parents=True, exist_ok=True)
    for name in [*sorted(sums["full_parts"]), *sorted(sums["incrementals"])]:
        dest = args.archive_dir / name
        have = dest.stat().st_size if dest.exists() else 0
        req = urllib.request.Request(f"{sums['base_url']}/{name}")
        if have:
            req.add_header("Range", f"bytes={have}-")
        print(f"downloading {name} (resume from {have} bytes)", file=sys.stderr)
        try:
            resp = urllib.request.urlopen(req, timeout=60)  # noqa: S310 - fixed https host
        except urllib.error.HTTPError as e:
            if e.code == 416:  # range not satisfiable: file already complete
                continue
            raise
        mode = "ab" if resp.status == 206 else "wb"
        with resp, dest.open(mode) as out:
            while chunk := resp.read(CHUNK):
                out.write(chunk)
    print("download complete; run `verify` next", file=sys.stderr)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    sums = load_checksums()
    ok = True
    for name, expected in sorted(sums["full_parts"].items()):
        actual = sha256_file(args.archive_dir / name)
        ok &= actual == expected
        print(f"{'OK  ' if actual == expected else 'FAIL'} {name}")
    full = hashlib.sha256()
    for path in part_paths(args.archive_dir, sums):
        with path.open("rb") as f:
            while chunk := f.read(CHUNK):
                full.update(chunk)
    match = full.hexdigest() == sums["full_zip_sha256"]
    ok &= match
    print(f"{'OK  ' if match else 'FAIL'} Kraken_OHLCVT_Full.zip (reassembled, streamed)")
    for name, expected in sorted(sums["incrementals"].items()):
        actual = sha256_file(args.archive_dir / name)
        ok &= actual == expected
        print(f"{'OK  ' if actual == expected else 'FAIL'} {name}")
    print("all checksums match" if ok else "CHECKSUM MISMATCH - do not convert", file=sys.stderr)
    return 0 if ok else 1


# --- convert / crossval (pandas + Freqtrade; run in the sandbox) -------------------------


def read_csv_from_zip(zf: zipfile.ZipFile, member: str):
    import pandas as pd

    with zf.open(member) as fh:
        return pd.read_csv(
            fh,
            header=None,
            names=["timestamp", "open", "high", "low", "close", "volume", "trades"],
            dtype={"timestamp": "int64"},
        )


def merge_sources(frames: list[tuple[str, object]]):
    """Union candles from several archives; identical duplicates collapse, conflicts fail."""
    import pandas as pd

    tagged = [f.assign(source=name) for name, f in frames if len(f)]
    if not tagged:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), 0
    allrows = pd.concat(tagged, ignore_index=True)
    cols = ["open", "high", "low", "close", "volume"]
    dup = allrows[allrows.duplicated("timestamp", keep=False)]
    conflicts = int(dup.groupby("timestamp")[cols].nunique().gt(1).any(axis=1).sum()) if len(dup) else 0
    merged = allrows.drop_duplicates("timestamp", keep="first").sort_values("timestamp")
    return merged.reset_index(drop=True), conflicts


def validate(df, interval_s: int) -> dict:
    """Facts about a candle series; `errors` non-empty means it must not be used."""
    errors = []
    ts = df["timestamp"]
    if (ts % interval_s != 0).any():
        errors.append(f"{int((ts % interval_s != 0).sum())} timestamps off the {interval_s}s grid")
    if not ts.is_monotonic_increasing or ts.duplicated().any():
        errors.append("timestamps not strictly increasing")
    bad_ohlc = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (df["volume"] < 0)
    )
    if bad_ohlc.any():
        errors.append(f"{int(bad_ohlc.sum())} rows fail OHLC sanity")
    steps = ts.diff().dropna() // interval_s
    missing = int((steps - 1).clip(lower=0).sum())
    rng = (df["high"] - df["low"]) / df["close"]
    widest = df.assign(range=rng).nlargest(3, "range")
    return {
        "errors": errors,
        "rows": len(df),
        "first": int(ts.iloc[0]),
        "last": int(ts.iloc[-1]),
        "missing_intervals": missing,
        "largest_gap_intervals": int(steps.max() - 1) if len(steps) else 0,
        "widest_bars": [
            {"timestamp": int(r.timestamp), "range_over_close": round(float(r.range), 4)}
            for r in widest.itertuples()
        ],
    }


def cmd_convert(args: argparse.Namespace) -> int:
    import pandas as pd
    from freqtrade.data.history.datahandlers.idatahandler import get_datahandler
    from freqtrade.enums import CandleType

    sums = load_checksums()
    reader = io.BufferedReader(MultiPartReader(part_paths(args.archive_dir, sums)), CHUNK)
    sources = [("Kraken_OHLCVT_Full.zip", zipfile.ZipFile(reader))]
    sources += [(n, zipfile.ZipFile(args.archive_dir / n)) for n in sorted(sums["incrementals"])]
    manifests = {n: json.loads(z.read("MANIFEST.json")) for n, z in sources}

    args.out.mkdir(parents=True, exist_ok=True)
    handler = get_datahandler(args.out, data_format="feather")
    report: dict = {
        "source_checksums": {"full_zip_sha256": sums["full_zip_sha256"], **sums["incrementals"]},
        "manifests": manifests,
        "series": {},
    }
    failed = False
    for pair in load_pairs():
        for timeframe, minutes in TIMEFRAMES.items():
            member = f"{archive_symbol(pair)}_{minutes}.csv"
            frames = [(n, read_csv_from_zip(z, member)) for n, z in sources if member in z.namelist()]
            merged, conflicts = merge_sources(frames)
            facts = validate(merged, minutes * 60) if len(merged) else {"errors": ["no rows"]}
            if conflicts:
                facts["errors"].append(f"{conflicts} timestamps disagree between archives")
            key = f"{pair} {timeframe}"
            if facts["errors"]:
                failed = True
                report["series"][key] = facts
                print(f"FAIL {key}: {facts['errors']}", file=sys.stderr)
                continue
            out = pd.DataFrame(
                {
                    "date": pd.to_datetime(merged["timestamp"], unit="s", utc=True),
                    **{c: merged[c].astype("float64") for c in ["open", "high", "low", "close", "volume"]},
                }
            )
            handler.ohlcv_store(pair, timeframe, out, CandleType.SPOT)
            stored = args.out / f"{pair.replace('/', '_')}-{timeframe}.feather"
            facts["feather_sha256"] = sha256_file(stored)
            facts["first_utc"] = str(out["date"].iloc[0])
            facts["last_utc"] = str(out["date"].iloc[-1])
            facts["sources"] = [n for n, f in frames if len(f)]
            report["series"][key] = facts
            print(
                f"OK   {key}: {facts['rows']} candles {facts['first_utc']} -> {facts['last_utc']}, "
                f"{facts['missing_intervals']} missing intervals",
                file=sys.stderr,
            )
    snapshot = hashlib.sha256(
        json.dumps({k: v.get("feather_sha256") for k, v in sorted(report["series"].items())}).encode()
    ).hexdigest()
    report["data_snapshot_id"] = snapshot[:16]
    (args.out / REPORT_NAME).write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"data_snapshot_id {report['data_snapshot_id']}", file=sys.stderr)
    return 1 if failed else 0


def cmd_crossval(args: argparse.Namespace) -> int:
    import pandas as pd

    threshold = args.threshold
    rows = []
    for pair in load_pairs():
        base, _ = pair.split("/")
        for timeframe in TIMEFRAMES:
            k_path = args.out / f"{base}_USD-{timeframe}.feather"
            b_path = args.binance_dir / f"{base}_USDT-{timeframe}.feather"
            if not (k_path.exists() and b_path.exists()):
                continue
            k = pd.read_feather(k_path)[["date", "close"]]
            b = pd.read_feather(b_path)[["date", "close"]]
            m = k.merge(b, on="date", suffixes=("_kraken", "_binance"))
            dev = (m["close_kraken"] / m["close_binance"] - 1).abs()
            rows.append(
                {
                    "series": f"{pair} {timeframe}",
                    "overlap_bars": len(m),
                    "first": str(m["date"].min()),
                    "last": str(m["date"].max()),
                    "median_abs_dev_pct": round(100 * float(dev.median()), 4),
                    "max_abs_dev_pct": round(100 * float(dev.max()), 3),
                    f"share_over_{threshold:g}pct": round(float((dev > threshold / 100).mean()), 5),
                }
            )
    print(json.dumps(rows, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    sub.add_parser("verify")
    sub.add_parser("convert")
    cv = sub.add_parser("crossval")
    cv.add_argument("--binance-dir", type=Path, default=DATA_ROOT / "binance")
    cv.add_argument("--threshold", type=float, default=0.5, help="flag |deviation| above this %%")
    args = parser.parse_args()
    return {"download": cmd_download, "verify": cmd_verify, "convert": cmd_convert, "crossval": cmd_crossval}[
        args.cmd
    ](args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Internal operator CLI (run inside the container; no network surface).

    python -m conductor.cli capital
    python -m conductor.cli record-transfer --amount 25 --destination "..." \\
        --tx-id ... --operator maduka [--at 2026-10-04T12:00:00Z] [--note ...]
    python -m conductor.cli value-trades
    python -m conductor.cli export-tax [--out file.csv]     (default: stdout)
    python -m conductor.cli halts [--all]
    python -m conductor.cli kill --operator NAME
    python -m conductor.cli nuclear --operator NAME --confirm-flatten-everything
    python -m conductor.cli clear-halt HALT_ID --operator NAME [--note ...]
    python -m conductor.cli backup-now
    python -m conductor.cli soak-check --started-at 2026-10-05T15:29:00Z [--hours 72]
    python -m conductor.cli isolation-check
    python -m conductor.cli exclude-balance --asset ETH --operator NAME [--amount N] [--note ...]

`kill` blocks new entries; `nuclear` also cancels open orders, market-exits every
position and stops the bot; `clear-halt` is the only way to resume (named
operator, logged). All three persist in the ledger first.

`backup-now` runs the nightly backup immediately (same code path and audit record as the
03:15 UTC job); it needs the BACKUP_B2_* settings. Use it to prove the B2 setup after a deploy.

`soak-check` (live-pilot gate, run against the dry-run ledger) exits 0 only when the soak window
has run for --hours (default 72) with no halt raised by the system itself and none active now.

`isolation-check` prints, for every whitelisted base asset, the exchange balance, what the ledger's
own open positions account for, what is excluded, and what is unexplained (R5); exit 1 if any
asset has an unexplained balance. `exclude-balance` records a pre-existing balance as NOT the
system's (AC5.4), by default exactly the unexplained amount; it cannot exceed what is held.

`record-transfer` only RECORDS a move you already made by hand on Kraken's own
interface. Nothing here can move money or talk to an exchange.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.application.backup import run_backup
from conductor.application.capital import PrincipalNotSetError, get_capital
from conductor.application.fence import record_manual_transfer
from conductor.application.halts import clear_halt, kill_switch, nuclear
from conductor.application.isolation import ExclusionError, isolation_rows, record_exclusion
from conductor.application.soak import DEFAULT_REQUIRED, check_soak
from conductor.application.tax import export_tax_csv, value_closed_trades
from conductor.infrastructure.config import Settings, load_settings
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.freqtrade_instances import build_instances
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.infrastructure.notifier import build_notifier
from conductor.infrastructure.observability import (
    build_backup_sources,
    build_object_store,
    build_snapshotter,
)


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise argparse.ArgumentTypeError("must be finite")
    return value


def _instant(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 timestamp: {text!r}") from exc
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp needs a timezone, e.g. 2026-10-04T12:00:00Z")
    return value.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="conductor.cli", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("capital", help="print principal / working profit / fenced / max deployed")
    t = sub.add_parser("record-transfer", help="record a manual transfer already made by hand")
    t.add_argument("--amount", type=_decimal, required=True, help="USD")
    t.add_argument("--destination", required=True)
    t.add_argument("--tx-id", required=True, help="exchange transaction/withdrawal id")
    t.add_argument("--operator", required=True)
    t.add_argument("--at", type=_instant, default=None, help="when it was made (default: now)")
    t.add_argument("--note", default=None)
    sub.add_parser("value-trades", help="fetch BoC rates and value closed trades in CAD")
    h = sub.add_parser("halts", help="list halts (active only unless --all)")
    h.add_argument("--all", action="store_true")
    k = sub.add_parser("kill", help="kill switch: block new entries on every instance")
    k.add_argument("--operator", required=True)
    n = sub.add_parser("nuclear", help="cancel orders, market-exit all positions, stop the bot")
    n.add_argument("--operator", required=True)
    n.add_argument(
        "--confirm-flatten-everything",
        action="store_true",
        help="required: this closes every open position at market",
    )
    c = sub.add_parser("clear-halt", help="clear a halt and resume (the only way back)")
    c.add_argument("halt_id", type=int)
    c.add_argument("--operator", required=True)
    c.add_argument("--note", default=None)
    s = sub.add_parser("soak-check", help="live-pilot gate: has the dry-run soak been clean?")
    s.add_argument("--started-at", type=_instant, required=True)
    s.add_argument("--hours", type=_decimal, default=DEFAULT_REQUIRED.total_seconds() / 3600)
    sub.add_parser("isolation-check", help="R5: show unexplained balances per whitelisted asset")
    x = sub.add_parser("exclude-balance", help="R5: record a pre-existing balance as not ours")
    x.add_argument("--asset", required=True, help="base asset code, e.g. ETH")
    x.add_argument("--operator", required=True)
    x.add_argument(
        "--amount",
        type=_decimal,
        default=None,
        help="total to exclude for this asset (default: everything currently unexplained)",
    )
    x.add_argument("--note", default=None)
    sub.add_parser("backup-now", help="run the nightly backup now (needs BACKUP_B2_* settings)")
    e = sub.add_parser("export-tax", help="write the CAD tax export as CSV")
    e.add_argument("--out", default="-", help="file path, or - for stdout")
    return p


def _halt_command(args: argparse.Namespace, ledger: SqliteLedger, settings: Settings) -> int:
    now = lambda: datetime.now(UTC)  # noqa: E731
    if args.command == "halts":
        with ledger.transaction(write=False) as repo:
            rows = repo.list_halts(200)
        shown = 0
        for halt, cleared_at, cleared_by in rows:
            if cleared_at is not None and not args.all:
                continue
            state = (
                "ACTIVE"
                if cleared_at is None
                else f"cleared {cleared_at:%Y-%m-%d %H:%M}Z by {cleared_by}"
            )
            scope = halt.instance or "all instances"
            print(f"#{halt.id} {halt.halt_type.value} [{scope}] {state} :: {halt.reason}")
            shown += 1
        if not shown:
            print("no active halts")
        return 0
    if args.command == "nuclear" and not args.confirm_flatten_everything:
        print(
            "ERROR: nuclear closes every open position at market; add --confirm-flatten-everything",
            file=sys.stderr,
        )
        return 1
    instances, closers = build_instances(settings)
    notifier, notifier_closers = build_notifier(settings)  # alerts from the host reach Telegram too
    closers = [*notifier_closers, *closers]
    try:
        if args.command == "clear-halt":
            report = clear_halt(
                ledger,
                instances,
                halt_id=args.halt_id,
                operator=args.operator,
                note=args.note,
                now=now,
                notifier=notifier,
            )
            print(
                ("cleared" if report.newly_cleared else "already cleared")
                + f" halt #{report.halt_id}"
            )
            for h in report.still_active:
                print(f"still active: #{h.id} {h.halt_type.value} :: {h.reason}")
            steps, ok = report.resumed, report.ok
        else:
            action = kill_switch if args.command == "kill" else nuclear
            hreport = action(ledger, instances, operator=args.operator, now=now, notifier=notifier)
            print(
                f"halt #{hreport.halt_id} {'engaged' if hreport.created else 'was already active'}"
            )
            steps, ok = hreport.steps, hreport.ok
        for s in steps:
            print(f"  {s.instance}: {s.step}: {'ok' if s.ok else 'FAILED ' + s.detail}")
        if not ok:
            print(
                "WARNING: not every step succeeded; the halt is recorded and will be re-applied "
                "by the risk cycle (a failed resume leaves Freqtrade paused: re-run clear-halt)",
                file=sys.stderr,
            )
        return 0 if ok else 1
    finally:
        for close in closers:
            close()


def _soak_check(ledger: SqliteLedger, args: argparse.Namespace) -> int:
    status = check_soak(
        ledger,
        started_at=args.started_at,
        now=datetime.now(UTC),
        required=timedelta(hours=float(args.hours)),
    )
    hours = status.elapsed.total_seconds() / 3600
    print(
        f"soak started {status.started_at:%Y-%m-%d %H:%MZ}; elapsed {hours:.1f} h of {args.hours} h"
    )
    for h in status.system_halts:
        print(f"  system halt since start: #{h.id} {h.halt_type.value} :: {h.reason}")
    for h in status.active_halts:
        print(f"  active halt now: #{h.id} {h.halt_type.value} :: {h.reason}")
    if not status.time_met:
        print("SOAK NOT MET: not enough time has passed")
    elif not status.clean:
        print("SOAK NOT CLEAN: see the halts above")
    else:
        print("SOAK MET")
    return 0 if status.ok else 1


def _isolation_command(args: argparse.Namespace, ledger: SqliteLedger, settings: Settings) -> int:
    instances, closers = build_instances(settings)
    try:
        inst = instances[0]
        if args.command == "isolation-check":
            rows = isolation_rows(ledger, inst)
            print(
                f"{'asset':8} {'exchange':>16} {'ledger':>16} {'excluded':>16} {'unexplained':>16}"
            )
            for r in rows:
                cells = (r.exchange_balance, r.ledger_holding, r.excluded, r.unexplained)
                shown = [f"{c.normalize():f}" if c else "0" for c in cells]
                print(f"{r.asset:8} " + " ".join(f"{c:>16}" for c in shown))
            bad = [r.asset for r in rows if r.unexplained > 0]
            print("R5 CHECK FAIL: unexplained " + ", ".join(bad) if bad else "R5 CHECK PASS")
            return 1 if bad else 0
        total = record_exclusion(
            ledger,
            inst,
            asset=args.asset,
            amount=args.amount,
            operator=args.operator,
            note=args.note,
            now=lambda: datetime.now(UTC),
        )
        print(f"excluded {total} {args.asset.strip().upper()} (total now excluded for that asset)")
        return 0
    except ExclusionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        for close in closers:
            close()


def _backup_now(ledger: SqliteLedger, settings: Settings) -> int:
    if not settings.backup_enabled:
        print("ERROR: backups are not configured (set the BACKUP_B2_* variables)", file=sys.stderr)
        return 1
    notifier, closers = build_notifier(settings)  # a failure alerts Telegram, as the job does
    try:
        report = run_backup(
            ledger,
            build_backup_sources(settings),
            build_snapshotter(),
            build_object_store(settings),
            mode=settings.trading_mode,
            now=lambda: datetime.now(UTC),
            notifier=notifier,
        )
    finally:
        for close in closers:
            close()
    for o in report.outcomes:
        print(f"{o.label}: {'ok ' + str(o.key) if o.ok else 'FAILED ' + o.detail}")
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ValidationError as exc:
        for err in exc.errors():
            print(f"CONFIG ERROR: {'.'.join(map(str, err['loc']))}: {err['msg']}", file=sys.stderr)
        return 2
    engine = create_db_engine(settings.database_url)
    ledger = SqliteLedger(create_session_factory(engine))
    try:
        if args.command == "capital":
            c = get_capital(ledger)
            for name in (
                "principal",
                "realized_profit",
                "fenced_total",
                "working_profit",
                "max_deployed_capital",
            ):
                print(f"{name}: {getattr(c, name)}")
        elif args.command == "record-transfer":
            rec = record_manual_transfer(
                ledger,
                amount=args.amount,
                destination=args.destination,
                exchange_tx_id=args.tx_id,
                transferred_at=args.at or datetime.now(UTC),
                operator=args.operator,
                note=args.note,
                now=lambda: datetime.now(UTC),
            )
            print(
                f"recorded transfer of {rec.amount} USD to {rec.destination} ({rec.exchange_tx_id})"
            )
        elif args.command == "value-trades":
            fx = BankOfCanadaFx()
            try:
                report = value_closed_trades(ledger, fx, now=lambda: datetime.now(UTC))
            finally:
                fx.close()
            print(f"valued={report.valued} pending={report.pending} failed={report.failed}")
            return 1 if report.failed else 0
        elif args.command in {"halts", "kill", "nuclear", "clear-halt"}:
            return _halt_command(args, ledger, settings)
        elif args.command == "soak-check":
            return _soak_check(ledger, args)
        elif args.command in {"isolation-check", "exclude-balance"}:
            return _isolation_command(args, ledger, settings)
        elif args.command == "backup-now":
            return _backup_now(ledger, settings)
        elif args.command == "export-tax":
            if args.out == "-":
                n = export_tax_csv(ledger, sys.stdout)
            else:
                with open(args.out, "w", newline="", encoding="utf-8") as fh:
                    n = export_tax_csv(ledger, fh)
            print(f"exported {n} trade(s)", file=sys.stderr)
    except (ValueError, PrincipalNotSetError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

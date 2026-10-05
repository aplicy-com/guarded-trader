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

`kill` blocks new entries; `nuclear` also cancels open orders, market-exits every
position and stops the bot; `clear-halt` is the only way to resume (named
operator, logged). All three persist in the ledger first.

`backup-now` runs the nightly backup immediately (same code path and audit record as the
03:15 UTC job); it needs the BACKUP_B2_* settings. Use it to prove the B2 setup after a deploy.

`record-transfer` only RECORDS a move you already made by hand on Kraken's own
interface. Nothing here can move money or talk to an exchange.
"""

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.application.backup import run_backup
from conductor.application.capital import PrincipalNotSetError, get_capital
from conductor.application.fence import record_manual_transfer
from conductor.application.halts import clear_halt, kill_switch, nuclear
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

"""Internal operator CLI (run inside the container; no network surface).

    python -m conductor.cli capital
    python -m conductor.cli record-transfer --amount 25 --destination "..." \\
        --tx-id ... --operator maduka [--at 2026-10-04T12:00:00Z] [--note ...]
    python -m conductor.cli value-trades
    python -m conductor.cli export-tax [--out file.csv]     (default: stdout)

`record-transfer` only RECORDS a move you already made by hand on Kraken's own
interface. Nothing here can move money or talk to an exchange.
"""

import argparse
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.application.capital import PrincipalNotSetError, get_capital
from conductor.application.fence import record_manual_transfer
from conductor.application.tax import export_tax_csv, value_closed_trades
from conductor.infrastructure.config import load_settings
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger


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
    e = sub.add_parser("export-tax", help="write the CAD tax export as CSV")
    e.add_argument("--out", default="-", help="file path, or - for stdout")
    return p


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

"""SQLite (WAL) engine and sessions, per ADR-0009. Conductor is the only writer."""

from collections.abc import Callable

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def _apply_pragmas(dbapi_conn: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def create_db_engine(database_url: str) -> Engine:
    engine = create_engine(database_url)
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def journal_mode_probe(engine: Engine) -> Callable[[], str]:
    def probe() -> str:
        with engine.connect() as conn:
            return str(conn.execute(text("PRAGMA journal_mode")).scalar_one())

    return probe

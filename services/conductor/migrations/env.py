import os

from alembic import context

from conductor.infrastructure.db import create_db_engine
from conductor.infrastructure.ledger_schema import metadata as target_metadata


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("sqlite:///"):
        raise SystemExit("DATABASE_URL must be set to a sqlite:/// URL to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_url())  # applies the WAL pragmas (ADR-0009)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

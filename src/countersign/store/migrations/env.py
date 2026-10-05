"""Alembic environment.

The application passes its own connection (`countersign.store.db.migrate`). Run from
the command line (`alembic upgrade head`), the database is the one of the settings.
"""

from alembic import context
from sqlalchemy import Connection

from countersign.config import get_settings
from countersign.store.db import create_db_engine
from countersign.store.models import Base


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        # SQLite cannot alter a column in place: later migrations rebuild the table.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    """Print the SQL instead of running it: `alembic upgrade head --sql`."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_db_engine(get_settings().database_url)
    with engine.connect() as own_connection:
        _run(own_connection)
        own_connection.commit()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()

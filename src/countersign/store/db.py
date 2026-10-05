"""Engine and sessions.

SQLite is the default and runs in WAL mode with a busy timeout, so that the API and
the workers can write from different threads or processes. Any other URL (PostgreSQL)
is passed to SQLAlchemy as is.

On SQLite the application controls its transactions itself. The driver's default is to
start one only before the first write, which leaves a SAVEPOINT taken earlier outside
of it: releasing that savepoint commits, and a later rollback no longer undoes it. Here
every transaction starts with BEGIN IMMEDIATE instead: it takes the write lock at
once, so two transactions never interleave and what one of them read is still true
when it writes.

The schema is owned by the Alembic migrations in `migrations/`; a test checks that
they and the models describe the same tables.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from countersign.store.models import Base


def create_db_engine(url: str) -> Engine:
    """An engine for `url`. Statement parameters are kept out of error messages:
    they are invoice data, and error messages end up in the logs."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True, hide_parameters=True)

    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url, connect_args={"timeout": 30, "check_same_thread": False}, hide_parameters=True
    )

    @event.listens_for(engine, "connect")
    def _configure(connection: Any, _record: Any) -> None:
        # The driver no longer decides when a transaction starts: see `_begin`.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def migrate(engine: Engine) -> None:
    """Bring the database to the latest schema revision; does nothing if it is there."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def create_schema(engine: Engine) -> None:
    """Create the tables straight from the models, without revision history.

    For tests and throw-away databases. A database that will be upgraded later must be
    created by `migrate`.
    """
    Base.metadata.create_all(engine)


SessionFactory = sessionmaker[Session]


def session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction(factory: SessionFactory) -> Iterator[Session]:
    """A session that commits on success and rolls back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()

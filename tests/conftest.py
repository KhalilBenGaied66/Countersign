import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from countersign.config import Settings
from countersign.datagen.build import reference_data
from countersign.eval.run import MemoryLedger
from countersign.master import MasterData
from countersign.pipeline.process import Pipeline, PipelineConfig, Tier
from countersign.store.db import SessionFactory, create_db_engine, session_factory
from countersign.store.models import Base
from tests.support import LARGE_MODEL, SMALL_MODEL, ScriptedModel, master_data

TIERS = (Tier("small", SMALL_MODEL), Tier("large", LARGE_MODEL))


@pytest.fixture
def master() -> MasterData:
    return master_data()


@pytest.fixture
def ledger() -> MemoryLedger:
    return MemoryLedger()


@pytest.fixture
def pipeline_for() -> Callable[..., tuple[Pipeline, ScriptedModel]]:
    """Build a pipeline around a scripted model: `pipeline_for(replies, master=..., **config)`."""

    def build(
        replies: dict[str, Any], *, master: MasterData | None = None, **config: Any
    ) -> tuple[Pipeline, ScriptedModel]:
        model = ScriptedModel(replies)
        config.setdefault("tiers", TIERS)
        return Pipeline(PipelineConfig(**config), model, master or master_data()), model

    return build


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """SQLite in a temporary directory, or the database server CI points the suite at.

    A SQLite file is new for every test. A server is shared, so it is emptied first,
    migration history included: each test starts from a database that does not exist.
    """
    shared = os.environ.get("COUNTERSIGN_TEST_DATABASE_URL")
    if not shared:
        return f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_db_engine(shared)
    with engine.begin() as connection:
        Base.metadata.drop_all(connection)
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    return shared


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(engine: Engine) -> SessionFactory:
    return session_factory(engine)


@pytest.fixture
def settings(tmp_path: Path, database_url: str) -> Settings:
    reference = tmp_path / "reference"
    reference.mkdir()
    for name, content in reference_data([]).items():
        (reference / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    return Settings(
        _env_file=None,
        database_url=database_url,
        storage_dir=tmp_path / "documents",
        export_dir=tmp_path / "export",
        reference_dir=reference,
        small_model=SMALL_MODEL,
        large_model=LARGE_MODEL,
        poll_interval_s=0.01,
        job_backoff_s=0.0,
        api_keys="",
        otlp_endpoint=None,
        replay_dir=None,
    )

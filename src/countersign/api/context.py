"""Everything a request handler or a worker needs, built once at start-up."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from prometheus_client import CollectorRegistry
from sqlalchemy import Engine, func, select

from countersign.config import Settings
from countersign.llm.cassette import ReplayClient
from countersign.llm.client import ModelClient, OllamaClient
from countersign.master import MasterData
from countersign.obs import metrics
from countersign.pipeline.process import Pipeline, PipelineConfig, Tier
from countersign.store import queue
from countersign.store.db import (
    SessionFactory,
    create_db_engine,
    migrate,
    session_factory,
    transaction,
)
from countersign.store.models import Document, utcnow


@dataclass
class Context:
    settings: Settings
    engine: Engine
    sessions: SessionFactory
    master: MasterData
    pipeline: Pipeline
    clock: Callable[[], datetime]
    # None when the application replays recorded answers instead of calling a server.
    ollama: OllamaClient | None
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)

    def today(self) -> date:
        """The date the checks compare a document with: the real one unless it is set."""
        return self.settings.today or self.clock().date()


def pipeline_config(settings: Settings) -> PipelineConfig:
    """The pipeline the application runs: small model first, large one on escalation."""
    return PipelineConfig(
        tiers=(Tier("small", settings.small_model), Tier("large", settings.large_model))
    )


def build_context(
    settings: Settings,
    *,
    client: ModelClient | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> Context:
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    sessions = session_factory(engine)
    master = MasterData.load(settings.reference_dir)

    ollama: OllamaClient | None = None
    if client is None:
        if settings.replay_dir is not None:
            client = ReplayClient(settings.replay_dir)
        else:
            ollama = OllamaClient(
                settings.ollama_url,
                timeout_s=settings.model_timeout_s,
                max_retries=settings.model_retries,
            )
            client = ollama
    context = Context(
        settings=settings,
        engine=engine,
        sessions=sessions,
        master=master,
        pipeline=Pipeline(pipeline_config(settings), client, master),
        clock=clock,
        ollama=ollama,
    )
    context.registry.register(metrics.BacklogCollector(lambda: _backlog(sessions)))
    return context


def _backlog(sessions: SessionFactory) -> dict[str, dict[str, int]]:
    with transaction(sessions) as session:
        rows = session.execute(select(Document.status, func.count()).group_by(Document.status))
        return {
            "jobs": queue.depth(session),
            "documents": {row.status: row[1] for row in rows},
        }

"""Application factory: one process serves the API, the review screen and the workers."""

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from countersign import __version__
from countersign.api.context import build_context
from countersign.api.guard import Guard
from countersign.api.routes import api, probes
from countersign.config import Settings, get_settings
from countersign.llm.client import ModelClient
from countersign.obs.logging import configure_logging, get_logger
from countersign.obs.tracing import configure_tracing
from countersign.store.models import utcnow
from countersign.worker import Worker, unique_worker_id

logger = get_logger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(
    settings: Settings | None = None,
    *,
    client: ModelClient | None = None,
    start_workers: bool = True,
    clock: Callable[[], datetime] = utcnow,
) -> FastAPI:
    """Build the application.

    `client` replaces the model server (tests pass a scripted one). `start_workers`
    is False when workers run as separate processes, or when a test drives one by hand.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        provider = configure_tracing(settings.otlp_endpoint)
        context = build_context(settings, client=client, clock=clock)
        app.state.context = context
        if not settings.parsed_api_keys():
            logger.warning("api_open", extra={"hint": "set COUNTERSIGN_API_KEYS outside localhost"})

        stop = threading.Event()
        threads = []
        for index in range(settings.workers if start_workers else 0):
            worker = Worker(
                sessions=context.sessions,
                pipeline=context.pipeline,
                settings=settings,
                # Unique across processes: the lease of a job is held by name.
                worker_id=unique_worker_id(f"worker-{index + 1}"),
                clock=clock,
            )
            thread = threading.Thread(
                target=worker.run, args=(stop,), name=worker.worker_id, daemon=True
            )
            thread.start()
            threads.append(thread)
        logger.info("started", extra={"version": __version__, "workers": len(threads)})
        try:
            yield
        finally:
            stop.set()
            for thread in threads:
                # A worker finishes the document it is on. If it cannot in time, the lease
                # on its job expires and another worker takes the job over.
                thread.join(timeout=10)
            if provider is not None:
                provider.shutdown()
            context.engine.dispose()

    app = FastAPI(
        title="Countersign",
        version=__version__,
        description="Supplier-invoice intake: model extraction, verified before posting.",
        lifespan=lifespan,
    )
    # In front of everything: keys, origin and size are checked before a body is read.
    app.add_middleware(Guard, settings=settings)
    app.include_router(probes)
    app.include_router(api, prefix="/api")
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app

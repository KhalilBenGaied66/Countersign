"""Command line.

countersign serve              API, review screen and workers in one process
countersign demo               the same on recorded model answers, with samples queued
countersign worker             a worker alone, for a deployment with several of them
countersign submit FILE...     queue PDF files without going through HTTP
countersign samples            queue documents of the evaluation dataset
countersign migrate            bring the database to the current schema
"""

import argparse
import signal
import sys
import threading
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from countersign.api.app import create_app
from countersign.api.context import build_context
from countersign.config import Settings, get_settings
from countersign.eval.dataset import load_samples
from countersign.obs.logging import configure_logging
from countersign.obs.tracing import configure_tracing
from countersign.store import documents
from countersign.store.db import create_db_engine, migrate, transaction
from countersign.worker import Worker


def _serve_app(settings: Settings, arguments: argparse.Namespace, *, workers: bool) -> int:
    refusal = settings.refusal_to_serve(arguments.host)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    app = create_app(settings, start_workers=workers)
    uvicorn.run(app, host=arguments.host, port=arguments.port, log_config=None, access_log=False)
    return 0


def _serve(arguments: argparse.Namespace) -> int:
    return _serve_app(get_settings(), arguments, workers=not arguments.no_workers)


def _demo(arguments: argparse.Namespace) -> int:
    """Serve the recorded samples: no model server, and the date of the recordings."""
    # Imported here: the evaluation code is not needed by the other commands.
    from countersign.eval.run import EVAL_TODAY  # noqa: PLC0415

    settings = get_settings().model_copy(
        update={"replay_dir": arguments.cassettes, "today": EVAL_TODAY}
    )
    refusal = settings.refusal_to_serve(arguments.host)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    directory = arguments.data / "dataset" / "test"
    samples = load_samples(directory)[: arguments.limit]
    queued = _queue_files(settings, [directory / sample.file for sample in samples], "samples")
    print(f"{queued} new documents queued from the test split")
    return _serve_app(settings, arguments, workers=True)


def _worker(_: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otlp_endpoint)
    context = build_context(settings)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        # SIGTERM is what an orchestrator sends; the document in progress is finished.
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    try:
        Worker(sessions=context.sessions, pipeline=context.pipeline, settings=settings).run(stop)
    finally:
        context.engine.dispose()
    return 0


def _migrate(_: argparse.Namespace) -> int:
    engine = create_db_engine(get_settings().database_url)
    try:
        migrate(engine)
    finally:
        engine.dispose()
    print("the database is at the current schema")
    return 0


def _queue_files(settings: Settings, paths: list[Path], source: str) -> int:
    context = build_context(settings)
    queued = 0
    try:
        for path in paths:
            with transaction(context.sessions) as session:
                document, created = documents.receive(
                    session,
                    settings.storage_dir,
                    path.read_bytes(),
                    filename=path.name,
                    source=source,
                    actor="cli",
                    now=context.clock(),
                    max_attempts=settings.job_max_attempts,
                )
                queued += created
                print(
                    f"{path.name}: document {document.id} "
                    f"({'queued' if created else 'already received'})"
                )
    finally:
        context.engine.dispose()
    return queued


def _submit(arguments: argparse.Namespace) -> int:
    missing = [path for path in arguments.files if not path.is_file()]
    if missing:
        print("not a file: " + ", ".join(str(path) for path in missing), file=sys.stderr)
        return 2
    _queue_files(get_settings(), arguments.files, "cli")
    return 0


def _samples(arguments: argparse.Namespace) -> int:
    directory = arguments.data / "dataset" / arguments.split
    samples = load_samples(directory)[: arguments.limit]
    queued = _queue_files(
        get_settings(), [directory / sample.file for sample in samples], "samples"
    )
    print(f"{queued} new documents queued from the {arguments.split} split")
    return 0


def _listening(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="countersign", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the API, the review screen and the workers")
    _listening(serve)
    serve.add_argument(
        "--no-workers", action="store_true", help="workers run as separate processes"
    )
    serve.set_defaults(run=_serve)

    demo = commands.add_parser(
        "demo", help="serve the recorded samples of the test split, without a model server"
    )
    _listening(demo)
    demo.add_argument("--limit", type=int, default=60, help="samples queued at start")
    demo.add_argument("--data", type=Path, default=Path("data"))
    demo.add_argument("--cassettes", type=Path, default=Path("evals/cassettes/test"))
    demo.set_defaults(run=_demo)

    worker = commands.add_parser("worker", help="process queued documents until stopped")
    worker.set_defaults(run=_worker)

    submit = commands.add_parser("submit", help="queue PDF files")
    submit.add_argument("files", nargs="+", type=Path)
    submit.set_defaults(run=_submit)

    samples = commands.add_parser("samples", help="queue documents of the evaluation dataset")
    samples.add_argument("--split", choices=("dev", "test", "confirm"), default="test")
    samples.add_argument("--limit", type=int, default=40)
    samples.add_argument("--data", type=Path, default=Path("data"))
    samples.set_defaults(run=_samples)

    migration = commands.add_parser("migrate", help="apply the database migrations")
    migration.set_defaults(run=_migrate)

    arguments = parser.parse_args(argv)
    try:
        get_settings()
    except ValidationError as error:
        # Say which setting is wrong, without a traceback and without its value.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
            for problem in error.errors()
        )
        print(f"configuration error: {problems}", file=sys.stderr)
        return 2
    result: int = arguments.run(arguments)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

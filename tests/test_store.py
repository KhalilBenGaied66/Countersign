"""The queue, the document record, and the worker that connects them to the pipeline."""

import io
import json
import logging
import random
import threading
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from countersign.config import Settings
from countersign.datagen.model import InvoiceData, compute_totals
from countersign.datagen.render import render_pdf
from countersign.datagen.scan import scan
from countersign.domain.schema import Invoice
from countersign.llm.client import ModelError
from countersign.master import MasterData
from countersign.obs.logging import JsonFormatter
from countersign.pipeline.process import Pipeline, PipelineConfig, Result
from countersign.store import documents, queue
from countersign.store.db import (
    SessionFactory,
    create_db_engine,
    migrate,
    session_factory,
    transaction,
)
from countersign.store.models import Document, Event, Export, Job
from countersign.worker import Worker
from tests.conftest import TIERS
from tests.support import (
    LARGE_MODEL,
    SMALL_MODEL,
    ScriptedModel,
    invoice_data,
    master_data,
    perfect_reply,
)

T0 = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def receive(
    sessions: SessionFactory, settings: Settings, pdf: bytes, name: str = "invoice.pdf"
) -> int:
    with transaction(sessions) as session:
        document, _ = documents.receive(
            session, settings.storage_dir, pdf, filename=name, source="test", actor="tester", now=T0
        )
        return document.id


def worker_for(
    sessions: SessionFactory,
    settings: Settings,
    replies: dict[str, Any],
    clock: Clock | None = None,
    master: MasterData | None = None,
    name: str = "w1",
) -> tuple[Worker, ScriptedModel]:
    model = ScriptedModel(replies)
    pipeline = Pipeline(PipelineConfig(tiers=TIERS), model, master or master_data())
    worker = Worker(
        sessions=sessions,
        pipeline=pipeline,
        settings=settings,
        worker_id=name,
        clock=clock or Clock(),
    )
    return worker, model


def load(sessions: SessionFactory, document_id: int) -> Document:
    with transaction(sessions) as session:
        document = session.get(Document, document_id)
        assert document is not None
        session.expunge(document)
        return document


def actions(sessions: SessionFactory, document_id: int) -> list[str]:
    with transaction(sessions) as session:
        events = session.scalars(
            select(Event).where(Event.document_id == document_id).order_by(Event.id)
        )
        return [event.action for event in events]


# ----------------------------------------------------------------------------- queue


def enqueue_documents(sessions: SessionFactory, count: int) -> list[int]:
    with transaction(sessions) as session:
        rows = []
        for index in range(count):
            document = Document(sha256=f"{index:064d}", filename=f"{index}.pdf", size_bytes=1)
            session.add(document)
            session.flush()
            queue.enqueue(session, document.id, now=T0 + timedelta(seconds=index))
            rows.append(document.id)
        return rows


def test_jobs_are_claimed_oldest_first_and_only_once(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 3)
    now = T0 + timedelta(minutes=1)
    claimed = []
    with transaction(sessions) as session:
        while (job := queue.claim(session, "w1", now=now, lease_seconds=60)) is not None:
            claimed.append(job.document_id)
            assert (job.status, job.locked_by, job.attempts) == ("running", "w1", 1)
    assert claimed == sorted(claimed)
    assert len(claimed) == 3


def test_a_job_is_not_claimed_before_its_time(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 1)
    with transaction(sessions) as session:
        assert queue.claim(session, "w1", now=T0 - timedelta(seconds=1), lease_seconds=60) is None
        assert queue.claim(session, "w1", now=T0, lease_seconds=60) is not None


def test_concurrent_workers_never_take_the_same_job(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 40)
    now = T0 + timedelta(minutes=5)
    taken: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def work(name: str) -> None:
        start.wait()
        while True:
            with transaction(sessions) as session:
                job = queue.claim(session, name, now=now, lease_seconds=60)
                if job is None:
                    return
                with lock:
                    taken.append(job.id)

    threads = [threading.Thread(target=work, args=(f"w{index}",)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(taken) == 40
    assert len(set(taken)) == 40


def test_an_expired_lease_makes_the_job_claimable_again(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 1)
    with transaction(sessions) as session:
        first = queue.claim(session, "dead-worker", now=T0, lease_seconds=60)
        assert first is not None
        assert queue.claim(session, "w2", now=T0 + timedelta(seconds=59), lease_seconds=60) is None
        again = queue.claim(session, "w2", now=T0 + timedelta(seconds=61), lease_seconds=60)
        assert again is not None
        assert (again.id, again.locked_by, again.attempts) == (first.id, "w2", 2)


def test_a_failed_job_backs_off_exponentially_then_is_parked(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 1)
    now = T0
    delays = []
    with transaction(sessions) as session:
        for _ in range(3):
            job = queue.claim(session, "w1", now=now, lease_seconds=60)
            assert job is not None
            retry = queue.fail(session, job, "boom", now=now, backoff_seconds=5)
            if retry:
                delays.append((job.run_after - now).total_seconds())
                now = job.run_after
        assert delays == [5, 10]
        assert (job.status, job.last_error, job.finished_at) == ("failed", "boom", now)
        assert queue.claim(session, "w1", now=now + timedelta(days=1), lease_seconds=60) is None
        assert queue.depth(session) == {"queued": 0, "running": 0, "done": 0, "failed": 1}


def test_a_job_whose_last_attempt_died_with_its_worker_is_parked(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 1)
    now = T0
    with transaction(sessions) as session:
        for _ in range(3):  # three workers die holding the job
            assert queue.claim(session, "w", now=now, lease_seconds=60) is not None
            now += timedelta(seconds=120)
        assert queue.claim(session, "w", now=now, lease_seconds=60) is None
        buried = queue.bury_exhausted(session, now=now)
        assert [job.status for job in buried] == ["failed"]
        assert queue.bury_exhausted(session, now=now) == []


def test_completing_a_job_releases_it(sessions: SessionFactory) -> None:
    enqueue_documents(sessions, 1)
    with transaction(sessions) as session:
        job = queue.claim(session, "w1", now=T0, lease_seconds=60)
        assert job is not None
        queue.complete(session, job, now=T0)
        assert (job.status, job.locked_by, job.locked_until) == ("done", None, None)
        assert queue.depth(session)["done"] == 1


# ------------------------------------------------------------------------- documents


def test_the_same_file_is_received_once(sessions: SessionFactory, settings: Settings) -> None:
    pdf = render_pdf(invoice_data("forez"))
    with transaction(sessions) as session:
        first, created = documents.receive(
            session, settings.storage_dir, pdf, filename="a.pdf", source="api", actor="ann", now=T0
        )
        again, created_again = documents.receive(
            session, settings.storage_dir, pdf, filename="b.pdf", source="api", actor="bob", now=T0
        )
        assert (created, created_again) == (True, False)
        assert first.id == again.id
        assert session.scalar(select(Job).where(Job.document_id == first.id)) is not None
        assert len(list(session.scalars(select(Job)))) == 1
    stored = documents.path_of(settings.storage_dir, first.sha256)
    assert stored.read_bytes() == pdf
    assert actions(sessions, first.id) == ["received"]


def test_timestamps_are_stored_in_utc_and_naive_ones_are_refused(sessions: SessionFactory) -> None:
    paris = datetime(2026, 7, 1, 13, 0, tzinfo=timezone(timedelta(hours=2)))
    with transaction(sessions) as session:
        session.add(Document(sha256="a" * 64, filename="a.pdf", size_bytes=1, received_at=paris))
    stored = load(sessions, 1).received_at
    assert stored == paris
    assert (stored.utcoffset(), stored.hour) == (timedelta(0), 11)
    with pytest.raises(Exception, match="naive datetime"), transaction(sessions) as session:
        session.add(
            Document(
                sha256="b" * 64, filename="b.pdf", size_bytes=1, received_at=datetime(2026, 7, 1)
            )
        )


def test_a_document_and_its_job_are_written_together_or_not_at_all(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The savepoint that guards a double upload must not commit the document alone."""

    def unreachable(*_: Any, **__: Any) -> None:
        raise RuntimeError("the queue cannot be written")

    monkeypatch.setattr(queue, "enqueue", unreachable)
    with pytest.raises(RuntimeError), transaction(sessions) as session:
        documents.receive(
            session,
            settings.storage_dir,
            render_pdf(invoice_data("forez")),
            filename="a.pdf",
            source="test",
            actor="tester",
            now=T0,
        )
    with transaction(sessions) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_receiving_a_file_stores_it_without_opening_it(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parsing an untrusted PDF belongs to the worker, not to the upload."""
    opened = []

    def reader(*_: Any, **__: Any) -> None:
        opened.append(True)
        raise ValueError("opened")

    monkeypatch.setattr("pypdf.PdfReader.__init__", reader)
    pdf = render_pdf(invoice_data("bureauplus", line_count=70))
    document_id = receive(sessions, settings, pdf)
    document = load(sessions, document_id)
    assert (document.status, document.page_count, opened) == ("queued", 0, [])
    assert documents.path_of(settings.storage_dir, document.sha256).read_bytes() == pdf
    assert not list(settings.storage_dir.glob("*.tmp"))


def test_a_database_error_does_not_carry_the_values_of_its_statement(
    sessions: SessionFactory,
) -> None:
    """Error messages are logged, and the values are invoice data."""
    with transaction(sessions) as session:
        session.add(Document(sha256="a" * 64, filename="Forez-2603-0187.pdf", size_bytes=1))
    again = Document(sha256="a" * 64, filename="Forez-2603-0187.pdf", size_bytes=1)
    with pytest.raises(IntegrityError) as raised, transaction(sessions) as session:
        session.add(again)
    assert "Forez-2603-0187" not in str(raised.value)


# ---------------------------------------------------------------------------- worker


def test_a_worker_processes_a_clean_invoice_end_to_end(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, model = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})

    assert worker.run_once() is True
    assert worker.run_once() is False  # nothing left

    document = load(sessions, document_id)
    assert document.status == "approved"
    assert document.decided_by == "system"
    assert document.vendor_id == data.vendor.vendor_id
    assert document.invoice_number == data.number
    assert document.total_gross == data.gross
    assert document.kept_tier == "small"
    assert document.mode == "text"
    assert document.model_seconds == 2.5
    assert document.result is not None
    assert Result.model_validate(document.result).outcome == "approved"
    assert Invoice.model_validate(document.invoice).total_gross == data.gross
    assert actions(sessions, document_id) == ["received", "processed"]
    assert model.calls[0].label == str(document_id)

    with transaction(sessions) as session:
        assert queue.depth(session) == {"queued": 0, "running": 0, "done": 1, "failed": 0}
        export = session.scalar(select(Export))
        assert export is not None
        assert export.delivered_at is not None

    exported = json.loads(
        (settings.export_dir / f"document-{document_id:08d}.json").read_text("utf-8")
    )
    assert exported["invoice_number"] == data.number
    assert exported["total_gross"] == str(data.gross)
    assert exported["vendor_id"] == data.vendor.vendor_id
    assert exported["approved_by"] == "system"


def test_exported_amounts_carry_their_two_decimals(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez", line_count=1)
    line = data.lines[0]
    line.quantity, line.unit_price, line.amount = Decimal(3), Decimal("507.30"), Decimal("1521.90")
    compute_totals(data)
    assert str(float(data.net)) == "1521.9"  # what a model writes as a JSON number
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    exported = json.loads(
        (settings.export_dir / f"document-{document_id:08d}.json").read_text("utf-8")
    )
    assert exported["total_net"] == "1521.90"
    assert exported["total_gross"] == str(data.gross)


def test_payment_goes_to_the_account_on_file_and_the_due_date_to_the_terms_on_file(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("dufresne")  # prints payment terms, no due date
    assert data.due_date is None
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    exported = json.loads(
        (settings.export_dir / f"document-{document_id:08d}.json").read_text("utf-8")
    )
    assert exported["pay_to_iban"] == data.vendor.iban
    assert exported["due_date"] == (data.issue_date + timedelta(days=45)).isoformat()


def test_a_document_that_fails_its_checks_waits_for_review_and_is_not_exported(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("fgs")  # supplier not on file
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    document = load(sessions, document_id)
    assert (document.status, document.reasons, document.decided_by) == (
        "review",
        ["supplier"],
        None,
    )
    with transaction(sessions) as session:
        assert session.scalar(select(Export)) is None
    assert not settings.export_dir.exists()


def copies(data: InvoiceData) -> tuple[bytes, bytes]:
    original = render_pdf(data)
    data.stamp = "DUPLICATA"
    return original, render_pdf(data)


def test_the_second_copy_of_an_invoice_is_set_aside(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    reply = perfect_reply(data)
    first, second = (receive(sessions, settings, pdf) for pdf in copies(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: reply})
    worker.run_once()
    worker.run_once()
    assert load(sessions, first).status == "approved"
    duplicate = load(sessions, second)
    assert (duplicate.status, duplicate.reasons, duplicate.decided_by) == (
        "duplicate",
        ["duplicate"],
        "system",
    )


def test_two_workers_racing_on_two_copies_cannot_both_approve(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Both read their copy before either result is saved: the index decides."""
    data = invoice_data("forez")
    reply = perfect_reply(data)
    first, second = (receive(sessions, settings, pdf) for pdf in copies(data))
    workers = [
        worker_for(sessions, settings, {SMALL_MODEL: reply}, name=name)[0] for name in ("w1", "w2")
    ]

    claims = [worker._claim() for worker in workers]
    results = [
        worker._process(claim[1], claim[2])
        for worker, claim in zip(workers, claims, strict=True)
        if claim
    ]
    assert [result.outcome for result in results] == ["approved", "approved"]
    for worker, claim, result in zip(workers, claims, results, strict=True):
        assert claim is not None
        worker._record_result(claim[0], claim[1], result)

    statuses = sorted(load(sessions, document_id).status for document_id in (first, second))
    assert statuses == ["approved", "duplicate"]
    with transaction(sessions) as session:
        assert len(list(session.scalars(select(Export)))) == 1


def test_a_model_outage_is_retried_then_the_document_is_marked_failed(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    down = {SMALL_MODEL: ModelError("unavailable"), LARGE_MODEL: ModelError("timeout")}
    worker, model = worker_for(sessions, settings, down)

    assert worker.run_once() is True
    assert load(sessions, document_id).status == "queued"  # back in the queue, not in review
    while worker.run_once():
        pass
    document = load(sessions, document_id)
    assert document.status == "failed"
    assert document.error is not None
    assert "model server" in document.error
    assert len(model.calls) == 6  # three attempts, two tiers each
    assert actions(sessions, document_id) == ["received", "failed"]


def test_a_document_recovers_when_the_model_comes_back(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    flaky = {
        SMALL_MODEL: [ModelError("unavailable"), perfect_reply(data)],
        LARGE_MODEL: ModelError("unavailable"),
    }
    worker, _ = worker_for(sessions, settings, flaky)
    worker.run_once()
    assert load(sessions, document_id).status == "queued"
    worker.run_once()
    assert load(sessions, document_id).status == "approved"


def test_a_document_the_model_cannot_read_goes_to_review_not_to_retry(
    sessions: SessionFactory, settings: Settings
) -> None:
    document_id = receive(sessions, settings, render_pdf(invoice_data("forez")))
    worker, model = worker_for(
        sessions,
        settings,
        {SMALL_MODEL: ModelError("truncated_output"), LARGE_MODEL: ModelError("too_long")},
    )
    worker.run_once()
    document = load(sessions, document_id)
    assert (document.status, document.reasons) == ("review", ["extraction_failed"])
    assert len(model.calls) == 2


def test_a_job_abandoned_by_a_dead_worker_is_finished_by_another(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    clock = Clock()
    dead, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="dead")
    alive, _ = worker_for(
        sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="alive"
    )

    claim = dead._claim()  # takes the job, then dies before doing anything
    assert claim is not None
    assert load(sessions, document_id).status == "processing"
    assert alive.run_once() is False  # the lease still holds

    clock.advance(seconds=dead.lease_s + 1)
    assert alive.run_once() is True
    assert load(sessions, document_id).status == "approved"


def test_a_worker_that_lost_its_lease_does_not_overwrite_the_result(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    clock = Clock()
    slow, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="slow")
    fast, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="fast")

    claim = slow._claim()
    assert claim is not None
    late_result = slow._process(claim[1], claim[2])
    clock.advance(seconds=slow.lease_s + 1)
    assert fast.run_once() is True
    slow._record_result(claim[0], claim[1], late_result)

    assert load(sessions, document_id).status == "approved"
    assert actions(sessions, document_id) == ["received", "processed"]  # processed once
    with transaction(sessions) as session:
        assert len(list(session.scalars(select(Export)))) == 1


def test_a_stored_file_that_vanished_fails_the_job_without_stopping_the_worker(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    documents.path_of(settings.storage_dir, load(sessions, document_id).sha256).unlink()
    worker, _ = worker_for(sessions, settings, {})
    while worker.run_once():
        pass
    document = load(sessions, document_id)
    assert document.status == "failed"
    assert document.error is not None
    assert "FileNotFoundError" in document.error


def test_the_worker_loop_stops_when_asked_and_survives_an_error(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    stop = threading.Event()
    calls = {"count": 0}
    original = worker.run_once

    def flaky_once() -> bool:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("database went away")
        worked = original()
        if not worked:
            stop.set()
        return worked

    monkeypatch.setattr(worker, "run_once", flaky_once)
    thread = threading.Thread(target=worker.run, args=(stop,))
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert load(sessions, document_id).status == "approved"


def test_the_worker_records_the_page_count_it_found(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("bureauplus", line_count=70)  # three pages
    document_id = receive(sessions, settings, render_pdf(data))
    assert load(sessions, document_id).page_count == 0  # an upload does not open the file
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    assert load(sessions, document_id).page_count == 3


def test_an_outage_during_one_reading_fails_the_job_instead_of_asking_a_person(
    sessions: SessionFactory, settings: Settings
) -> None:
    """A second reading that could not be made is not a reason to review the first."""
    data = invoice_data("forez")
    misread = perfect_reply(data)
    misread["total_gross"] += 100
    document_id = receive(sessions, settings, render_pdf(data))
    worker, model = worker_for(
        sessions, settings, {SMALL_MODEL: misread, LARGE_MODEL: ModelError("timeout")}
    )

    assert worker.run_once() is True
    assert load(sessions, document_id).status == "queued"
    while worker.run_once():
        pass
    document = load(sessions, document_id)
    assert document.status == "failed"
    assert document.error == "TransientFailure: model server: timeout"
    assert len(model.calls) == 6
    assert actions(sessions, document_id) == ["received", "failed"]


def test_a_scan_read_by_one_tier_only_waits_for_the_other(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    reply = perfect_reply(data)
    scanned = scan(render_pdf(data), random.Random(1))
    document_id = receive(sessions, settings, scanned)
    replies = {SMALL_MODEL: reply, LARGE_MODEL: [ModelError("unavailable"), reply]}
    worker, _ = worker_for(sessions, settings, replies)

    worker.run_once()
    assert load(sessions, document_id).status == "queued"  # not "review: two readings differ"
    worker.run_once()
    assert load(sessions, document_id).status == "approved"


def test_a_reading_that_passes_is_kept_whatever_failed_before_it(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    replies = {SMALL_MODEL: ModelError("timeout"), LARGE_MODEL: perfect_reply(data)}
    worker, _ = worker_for(sessions, settings, replies)
    worker.run_once()
    document = load(sessions, document_id)
    assert (document.status, document.kept_tier) == ("approved", "large")


def test_a_result_the_database_refuses_fails_the_job_with_its_own_error(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a lost worker, and not read again: the same value would be refused again."""
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, model = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})

    def refuse(*_: Any, **__: Any) -> None:
        raise DataError("UPDATE documents", {}, Exception("value too long for type varchar(64)"))

    monkeypatch.setattr(documents, "save_result", refuse)
    assert worker.run_once() is True
    document = load(sessions, document_id)
    assert document.status == "failed"
    assert document.error is not None
    assert "value too long" in document.error
    with transaction(sessions) as session:
        job = session.scalar(select(Job))
        assert job is not None
        assert (job.status, job.attempts, job.locked_by) == ("failed", 1, None)
    assert len(model.calls) == 1
    assert worker.run_once() is False


def test_a_failed_save_is_logged_without_the_values_it_tried_to_write(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logs carry identifiers and outcomes; a statement's parameters are invoice data."""
    data = invoice_data("forez")
    receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})

    def collide(session: Session, document: Document, *_: Any, **__: Any) -> None:
        session.add(Document(sha256=document.sha256, filename=data.vendor.name, size_bytes=1))
        session.flush()

    monkeypatch.setattr(documents, "save_result", collide)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("countersign.worker")
    logger.addHandler(handler)
    try:
        worker.run_once()
    finally:
        logger.removeHandler(handler)
    line = json.loads(stream.getvalue().splitlines()[-1])
    assert (line["event"], line["retry"]) == ("job_failed", True)
    assert "IntegrityError" in line["error"]
    assert "IntegrityError" in line["exception"]
    assert data.vendor.name not in stream.getvalue()


def test_an_error_while_saving_is_a_failed_attempt_like_any_other(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    save, calls = documents.save_result, []

    def flaky(*arguments: Any, **options: Any) -> None:
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("the disk is full")
        save(*arguments, **options)

    monkeypatch.setattr(documents, "save_result", flaky)
    assert worker.run_once() is True
    assert load(sessions, document_id).status == "queued"
    with transaction(sessions) as session:
        job = session.scalar(select(Job))
        assert job is not None
        assert (job.status, job.last_error) == ("queued", "RuntimeError: the disk is full")
    assert worker.run_once() is True
    assert load(sessions, document_id).status == "approved"


def test_an_approval_that_does_not_commit_exports_nothing(
    sessions: SessionFactory, settings: Settings
) -> None:
    """The file is what the accounting system acts on: it follows the commit."""
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    failed = []

    @sqlalchemy_event.listens_for(sessions, "before_commit")
    def refuse(session: Session) -> None:
        approving = any(
            isinstance(row, Document) and row.status == "approved"
            for row in session.identity_map.values()
        )
        if approving and not session.in_nested_transaction() and not failed:
            failed.append(True)
            raise RuntimeError("the commit fails")

    assert worker.run_once() is True
    sqlalchemy_event.remove(sessions, "before_commit", refuse)
    assert failed
    assert not settings.export_dir.exists() or not list(settings.export_dir.iterdir())
    assert load(sessions, document_id).status == "queued"
    with transaction(sessions) as session:
        assert session.scalar(select(Export)) is None

    assert worker.run_once() is True  # the next attempt goes through, and only then the file
    assert load(sessions, document_id).status == "approved"
    assert [path.name for path in settings.export_dir.iterdir()] == [
        f"document-{document_id:08d}.json"
    ]


def test_a_job_for_a_document_already_decided_is_closed_without_touching_it(
    sessions: SessionFactory, settings: Settings
) -> None:
    """A stray second job must not put an approved document back to work."""
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, model = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    with transaction(sessions) as session:
        queue.enqueue(session, document_id, now=T0)

    assert worker.run_once() is False
    document = load(sessions, document_id)
    assert (document.status, document.decided_by, document.reasons) == ("approved", "system", [])
    assert len(model.calls) == 1
    assert actions(sessions, document_id) == ["received", "processed"]
    with transaction(sessions) as session:
        assert queue.depth(session) == {"queued": 0, "running": 0, "done": 2, "failed": 0}
        assert len(list(session.scalars(select(Export)))) == 1


def test_a_result_for_a_document_no_longer_in_progress_is_dropped(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Whatever moved the document on while it was being read, the reading is too late."""
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    claim = worker._claim()
    assert claim is not None
    result = worker._process(claim[1], claim[2])
    with transaction(sessions) as session:
        document = documents.locked(session, document_id)
        assert document is not None
        documents.mark_failed(session, document, "set aside by hand", now=T0)

    worker._record_result(claim[0], claim[1], result)
    document = load(sessions, document_id)
    assert (document.status, document.error, document.result) == (
        "failed",
        "set aside by hand",
        None,
    )
    with transaction(sessions) as session:
        assert queue.depth(session)["done"] == 1
        assert session.scalar(select(Export)) is None


def test_a_document_whose_last_attempt_died_with_its_worker_is_marked_failed(
    sessions: SessionFactory, settings: Settings
) -> None:
    document_id = receive(sessions, settings, render_pdf(invoice_data("forez")))
    clock = Clock()
    dead, _ = worker_for(sessions, settings, {}, clock, name="dead")
    other, _ = worker_for(sessions, settings, {}, clock, name="other")
    for _attempt in range(settings.job_max_attempts):
        assert dead._claim() is not None
        clock.advance(seconds=dead.lease_s + 1)

    assert other.run_once() is False
    document = load(sessions, document_id)
    assert (document.status, document.error) == ("failed", "worker lost during the last attempt")
    assert actions(sessions, document_id) == ["received", "failed"]


def test_a_document_still_being_read_is_not_taken_by_another_worker(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Nothing renews a lease: it has to outlast the slowest document."""
    data = invoice_data("forez")
    receive(sessions, settings, render_pdf(data))
    clock = Clock()
    slow, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="slow")
    other, _ = worker_for(
        sessions, settings, {SMALL_MODEL: perfect_reply(data)}, clock, name="other"
    )
    tries = settings.model_retries + 1
    assert slow.lease_s > len(TIERS) * tries * settings.model_timeout_s > settings.job_lease_s

    assert slow._claim() is not None
    clock.advance(seconds=len(TIERS) * tries * settings.model_timeout_s)
    assert other.run_once() is False
    clock.advance(seconds=slow.lease_s)
    assert other.run_once() is True


def test_workers_have_names_that_do_not_repeat(
    sessions: SessionFactory, settings: Settings
) -> None:
    """A lease is held by name: two workers with one name would share it."""
    pipeline = Pipeline(PipelineConfig(tiers=TIERS), ScriptedModel({}), master_data())
    names = {
        Worker(sessions=sessions, pipeline=pipeline, settings=settings).worker_id for _ in range(20)
    }
    assert len(names) == 20
    assert all(len(name) <= 64 for name in names)  # the width of jobs.locked_by


def test_a_fixed_today_keeps_dated_documents_from_ageing(
    sessions: SessionFactory, settings: Settings
) -> None:
    """The recorded samples are dated 2026: replayed years later they must still pass."""
    later = Clock(datetime(2028, 1, 15, 9, 0, tzinfo=UTC))
    first, second = invoice_data("forez"), invoice_data("forez", seed=3, sequence=190)
    replies = {SMALL_MODEL: [perfect_reply(first), perfect_reply(second)]}

    aged = receive(sessions, settings, render_pdf(first))
    worker, _ = worker_for(sessions, settings, replies, later)
    worker.run_once()
    assert (load(sessions, aged).status, load(sessions, aged).reasons) == ("review", ["dates"])

    settings.today = date(2026, 7, 1)
    fresh = receive(sessions, settings, render_pdf(second))
    worker.run_once()
    assert load(sessions, fresh).status == "approved"


# --------------------------------------------------------------- reviewer's decision


def in_review(sessions: SessionFactory, settings: Settings, data: InvoiceData) -> int:
    """A document stopped because both models misread its gross total."""
    document_id = receive(sessions, settings, render_pdf(data))
    wrong = perfect_reply(data)
    wrong["total_gross"] += 100
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: wrong, LARGE_MODEL: wrong})
    worker.run_once()
    assert load(sessions, document_id).status == "review"
    return document_id


def test_a_reviewer_approves_with_a_correction(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = in_review(sessions, settings, data)
    master = master_data()
    with transaction(sessions) as session:
        document = session.get(Document, document_id)
        assert document is not None
        corrected = Invoice.model_validate(document.invoice).model_copy(
            update={"total_gross": data.gross}
        )
        documents.decide(
            session,
            document,
            master,
            action="approve",
            reviewer="ann",
            now=T0,
            invoice=corrected,
            comment="typo",
        )
    assert documents.deliver_exports(sessions, settings.export_dir, now=T0) == 1
    assert documents.deliver_exports(sessions, settings.export_dir, now=T0) == 0

    document = load(sessions, document_id)
    assert (document.status, document.decided_by, document.total_gross) == (
        "approved",
        "ann",
        data.gross,
    )
    with transaction(sessions) as session:
        event = session.scalars(select(Event).order_by(Event.id.desc())).first()
        assert event is not None
        assert (event.actor, event.action) == ("ann", "approved")
        assert event.detail["corrected"] == ["total_gross"]
        assert event.detail["comment"] == "typo"
    exported = json.loads(
        (settings.export_dir / f"document-{document_id:08d}.json").read_text("utf-8")
    )
    assert exported["approved_by"] == "ann"
    assert Decimal(exported["total_gross"]) == data.gross


def test_a_reviewer_rejects(sessions: SessionFactory, settings: Settings) -> None:
    document_id = in_review(sessions, settings, invoice_data("forez"))
    with transaction(sessions) as session:
        document = session.get(Document, document_id)
        assert document is not None
        documents.decide(session, document, master_data(), action="reject", reviewer="ann", now=T0)
    document = load(sessions, document_id)
    assert (document.status, document.decided_by) == ("rejected", "ann")
    with transaction(sessions) as session:
        assert session.scalar(select(Export)) is None


def test_only_a_document_in_review_can_be_decided(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    approved = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    with transaction(sessions) as session:
        document = session.get(Document, approved)
        assert document is not None
        with pytest.raises(ValueError, match="not waiting for review"):
            documents.decide(
                session, document, master_data(), action="approve", reviewer="ann", now=T0
            )

    waiting = in_review(sessions, settings, invoice_data("forez", seed=3, sequence=190))
    with transaction(sessions) as session:
        document = session.get(Document, waiting)
        assert document is not None
        with pytest.raises(ValueError, match="unknown action"):
            documents.decide(
                session, document, master_data(), action="escalate", reviewer="ann", now=T0
            )


def test_a_reviewer_cannot_approve_a_number_that_is_already_approved(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    approved = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    assert load(sessions, approved).status == "approved"

    other = invoice_data("forez", seed=3, sequence=190)
    document_id = in_review(sessions, settings, other)
    with transaction(sessions) as session:
        document = session.get(Document, document_id)
        assert document is not None
        same_number = Invoice.model_validate(document.invoice).model_copy(
            update={"invoice_number": data.number, "total_gross": other.gross}
        )
        with pytest.raises(documents.AlreadyApproved):
            documents.decide(
                session,
                document,
                master_data(),
                action="approve",
                reviewer="ann",
                now=T0,
                invoice=same_number,
            )
        session.rollback()
    assert load(sessions, document_id).status == "review"


def test_an_approval_and_its_audit_event_are_one_transaction(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Approving as extracted writes nothing before its savepoint: it must not commit there."""
    document_id = in_review(sessions, settings, invoice_data("forez"))

    def approve_then_die() -> None:
        with transaction(sessions) as session:
            document = documents.locked(session, document_id)
            assert document is not None
            documents.decide(
                session, document, master_data(), action="approve", reviewer="ann", now=T0
            )
            raise RuntimeError("the request dies before its commit")

    with pytest.raises(RuntimeError, match="dies before its commit"):
        approve_then_die()
    assert load(sessions, document_id).status == "review"
    assert actions(sessions, document_id) == ["received", "processed"]
    with transaction(sessions) as session:
        assert session.scalar(select(Export)) is None


def test_a_document_already_exported_is_not_mistaken_for_a_duplicate_of_another(
    sessions: SessionFactory, settings: Settings
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    with transaction(sessions) as session:
        document = documents.locked(session, document_id)
        assert document is not None
        with pytest.raises(ValueError, match="already been exported"):
            documents._approve(session, document, master_data(), "ann", T0)


def test_the_ledger_remembers_an_invoice_a_person_refused(
    sessions: SessionFactory, settings: Settings
) -> None:
    """Sent again as another file, it must not be approved as if nobody had looked."""
    data = invoice_data("forez")
    refused = in_review(sessions, settings, data)
    with transaction(sessions) as session:
        document = documents.locked(session, refused)
        assert document is not None
        documents.decide(session, document, master_data(), action="reject", reviewer="ann", now=T0)

    prior = documents.SessionLedger(sessions, document_id=0).find(
        data.vendor.vendor_id, data.number
    )
    assert prior is not None
    assert (prior.document_id, prior.rejected_by, prior.issue_date) == (
        str(refused),
        "ann",
        data.issue_date,
    )
    assert (
        documents.SessionLedger(sessions, refused).find(data.vendor.vendor_id, data.number) is None
    )


def test_the_ledger_prefers_a_document_taken_in_and_ignores_what_the_system_set_aside(
    sessions: SessionFactory,
) -> None:
    def row(number: int, status: str, decided_by: str | None, invoice_number: str) -> Document:
        return Document(
            sha256=f"{number:064d}",
            filename=f"{number}.pdf",
            size_bytes=1,
            status=status,
            decided_by=decided_by,
            vendor_id="V-1",
            invoice_number=invoice_number,
            document_type="invoice",
            total_gross=Decimal("120.00"),
            issue_date=date(2026, 3, number),
        )

    with transaction(sessions) as session:
        for document in (
            row(1, "rejected", "ann", "N-1"),
            row(2, "review", None, "N-1"),
            row(3, "approved", "system", "N-1"),
            row(4, "rejected", "system", "N-2"),  # set aside as "not an invoice"
            row(5, "duplicate", "system", "N-2"),
        ):
            session.add(document)
            session.flush()
    with transaction(sessions) as session:
        ledger = documents.DatabaseLedger(session, document_id=0)
        prior = ledger.find("V-1", "N-1")
        assert prior is not None
        assert (prior.document_id, prior.rejected_by, prior.issue_date) == (
            "2",
            None,
            date(2026, 3, 2),
        )
        assert ledger.find("V-1", "N-2") is None


def test_a_document_is_never_queued_twice(sessions: SessionFactory, settings: Settings) -> None:
    document_id = in_review(sessions, settings, invoice_data("forez"))
    with transaction(sessions) as session:
        document = documents.locked(session, document_id)
        assert document is not None
        documents.requeue(session, document, actor="ann", now=T0, max_attempts=3)
    with transaction(sessions) as session:
        document = documents.locked(session, document_id)
        assert document is not None
        with pytest.raises(ValueError, match="queued cannot be reprocessed"):
            documents.requeue(session, document, actor="bob", now=T0, max_attempts=3)
    with transaction(sessions) as session:
        assert queue.depth(session) == {"queued": 1, "running": 0, "done": 1, "failed": 0}
    assert actions(sessions, document_id) == ["received", "processed", "requeued"]


def test_requeueing_a_failed_document(sessions: SessionFactory, settings: Settings) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    down, _ = worker_for(
        sessions,
        settings,
        {SMALL_MODEL: ModelError("unavailable"), LARGE_MODEL: ModelError("unavailable")},
    )
    while down.run_once():
        pass
    assert load(sessions, document_id).status == "failed"

    with transaction(sessions) as session:
        document = session.get(Document, document_id)
        assert document is not None
        documents.requeue(session, document, actor="ann", now=T0, max_attempts=3)
    up, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    up.run_once()
    assert load(sessions, document_id).status == "approved"
    assert actions(sessions, document_id) == ["received", "failed", "requeued", "processed"]


def test_statistics(sessions: SessionFactory, settings: Settings) -> None:
    clean = invoice_data("forez")
    unknown = invoice_data("fgs")
    quote = invoice_data("securipro")
    quote.kind = "quote"
    for data in (clean, unknown, quote):
        receive(sessions, settings, render_pdf(data))
    replies = [perfect_reply(clean), perfect_reply(unknown), perfect_reply(quote)]
    worker, model = worker_for(
        sessions, settings, {SMALL_MODEL: replies, LARGE_MODEL: perfect_reply(quote)}
    )
    while worker.run_once():
        pass
    with transaction(sessions) as session:
        stats = documents.statistics(session)
    assert stats["by_status"] == {
        "queued": 0,
        "processing": 0,
        "approved": 1,
        "review": 1,
        "rejected": 1,
        "duplicate": 0,
        "failed": 0,
    }
    assert stats["processed"] == 3
    assert stats["approved_automatically"] == 1
    assert stats["automation_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["review_reasons"] == {"supplier": 1}
    # Whether the quote needed a second reading is the pipeline's business, not this one's.
    assert sum(stats["kept_tier"].values()) == 3
    assert stats["mean_model_seconds"] == pytest.approx(2.5 * len(model.calls) / 3, abs=0.01)
    assert stats["exports_pending"] == 0


def test_an_export_file_appears_whole_under_its_document_id_or_not_at_all(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    rename = Path.replace

    def interrupted(self: Path, target: Path) -> Path:
        if self.suffix == ".tmp" and Path(target).suffix == ".json":
            raise OSError("the disk is full")
        return rename(self, target)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "replace", interrupted)
        worker.run_once()
    # Written next to the final name and never renamed: the consumer saw nothing.
    assert load(sessions, document_id).status == "approved"
    assert list(settings.export_dir.iterdir()) == []
    with transaction(sessions) as session:
        export = session.scalar(select(Export))
        assert export is not None
        assert export.delivered_at is None

    assert worker.run_once() is False  # an idle worker delivers what is pending
    files = sorted(path.name for path in settings.export_dir.iterdir())
    assert files == [f"document-{document_id:08d}.json"]
    exported = json.loads((settings.export_dir / files[0]).read_text("utf-8"))
    assert exported["document_id"] == document_id


def test_a_delivery_interrupted_after_the_file_is_repeated_onto_the_same_file(
    sessions: SessionFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file is written before its row is marked: the reverse could lose an export."""
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})
    monkeypatch.setattr(worker, "_deliver", lambda: None)
    worker.run_once()
    assert not settings.export_dir.exists()

    marking = []

    @sqlalchemy_event.listens_for(sessions, "before_commit")
    def crash(session: Session) -> None:
        if (settings.export_dir / f"document-{document_id:08d}.json").exists() and not marking:
            marking.append(True)
            raise RuntimeError("killed between the file and the mark")

    with pytest.raises(RuntimeError):
        documents.deliver_exports(sessions, settings.export_dir, now=T0)
    sqlalchemy_event.remove(sessions, "before_commit", crash)
    with transaction(sessions) as session:
        assert session.scalar(select(func.count()).where(Export.delivered_at.is_(None))) == 1

    assert documents.deliver_exports(sessions, settings.export_dir, now=T0) == 1
    assert documents.deliver_exports(sessions, settings.export_dir, now=T0) == 0
    assert [path.name for path in settings.export_dir.iterdir()] == [
        f"document-{document_id:08d}.json"
    ]


# ------------------------------------------------------------------------ migrations


def test_migrations_build_the_schema_the_models_describe(tmp_path: Path) -> None:
    """A column added to a model without a migration fails here, not in production."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from countersign.store.models import Base

    engine = create_db_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    migrate(engine)
    migrate(engine)  # running it again changes nothing
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == []


def test_a_migrated_database_refuses_a_second_approval_and_nothing_else(
    database_url: str,
) -> None:
    """The comparison above does not see the WHERE of the index; this one does.

    It runs on whichever database the suite is pointed at, PostgreSQL included.
    """

    def row(number: int, status: str) -> Document:
        return Document(
            sha256=f"{number:064d}",
            filename=f"{number}.pdf",
            size_bytes=1,
            status=status,
            vendor_id="V-1",
            invoice_number="N-1",
        )

    engine = create_db_engine(database_url)
    migrate(engine)
    migrated = session_factory(engine)
    try:
        with transaction(migrated) as session:
            session.add_all([row(1, "review"), row(2, "rejected"), row(3, "approved")])
        with pytest.raises(IntegrityError), transaction(migrated) as session:
            session.add(row(4, "approved"))
    finally:
        engine.dispose()


def test_a_migrated_database_takes_a_document_end_to_end(
    tmp_path: Path, settings: Settings
) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    migrate(engine)
    migrated = session_factory(engine)
    data = invoice_data("forez")
    document_id = receive(migrated, settings, render_pdf(data))
    worker, _ = worker_for(migrated, settings, {SMALL_MODEL: perfect_reply(data)})
    worker.run_once()
    assert load(migrated, document_id).status == "approved"
    copy = invoice_data("forez")
    copy.stamp = "DUPLICATA"
    duplicate_id = receive(migrated, settings, render_pdf(copy))
    worker.run_once()
    assert load(migrated, duplicate_id).status == "duplicate"
    engine.dispose()


def test_an_approval_survives_an_export_directory_that_cannot_be_written(
    sessions: SessionFactory, settings: Settings, tmp_path: Path
) -> None:
    data = invoice_data("forez")
    document_id = receive(sessions, settings, render_pdf(data))
    blocked = tmp_path / "export"
    blocked.write_text("a file where the directory should be")  # mkdir will fail
    worker, _ = worker_for(sessions, settings, {SMALL_MODEL: perfect_reply(data)})

    assert worker.run_once() is True
    assert load(sessions, document_id).status == "approved"
    with transaction(sessions) as session:
        export = session.scalar(select(Export))
        assert export is not None
        assert export.delivered_at is None  # still owed to the accounting system

    blocked.unlink()
    assert worker.run_once() is False  # an idle worker delivers what is pending
    with transaction(sessions) as session:
        export = session.scalar(select(Export))
        assert export is not None
        assert export.delivered_at is not None
    assert (settings.export_dir / f"document-{document_id:08d}.json").is_file()

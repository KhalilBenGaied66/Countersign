"""Take jobs from the queue and run the pipeline on their documents.

A worker holds no state of its own: everything it needs is in the job row and the
stored file, so workers can be added, stopped or killed at any time. The model call is
made outside any database transaction; the result is written in one transaction
together with the audit event, the outbox row and the completion of the job. Export
files are written after that transaction has committed.
"""

import socket
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import DataError

from countersign.config import Settings
from countersign.obs import metrics
from countersign.obs.logging import get_logger
from countersign.pipeline.process import Pipeline, Result
from countersign.store import documents, queue
from countersign.store.db import SessionFactory, transaction
from countersign.store.documents import SessionLedger
from countersign.store.models import PROCESSING, QUEUED, Job, utcnow

logger = get_logger(__name__)

# Model failures that say nothing about the document: the job is retried later instead
# of sending the document to a person.
_TRANSIENT_ERRORS = frozenset({"unavailable", "timeout"})


class TransientFailure(Exception):
    """The document could not be processed for a reason that may pass."""


def unique_worker_id(label: str = "") -> str:
    """A name no other worker has, in this process or another one.

    The lease of a job is held by name: two workers with the same name would each take
    the other's lease for their own.
    """
    return f"{label or socket.gethostname()[:32]}-{uuid4().hex[:12]}"


class Worker:
    def __init__(
        self,
        *,
        sessions: SessionFactory,
        pipeline: Pipeline,
        settings: Settings,
        worker_id: str | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.sessions = sessions
        self.pipeline = pipeline
        self.settings = settings
        self.clock = clock
        self.worker_id = worker_id or unique_worker_id()
        self.lease_s = settings.lease_seconds(len(pipeline.config.tiers))

    def run(self, stop: threading.Event) -> None:
        """Process jobs until `stop` is set; the job in progress is finished first."""
        logger.info("worker_started", extra={"worker": self.worker_id, "lease_s": self.lease_s})
        while not stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                # The loop must survive anything, including a database that went away.
                logger.exception("worker_iteration_failed", extra={"worker": self.worker_id})
                worked = False
            if not worked:
                stop.wait(self.settings.poll_interval_s)
        logger.info("worker_stopped", extra={"worker": self.worker_id})

    def run_once(self) -> bool:
        """Claim and process one job. Returns False when the queue had nothing ready."""
        claimed = self._claim()
        if claimed is None:
            # Nothing to read: use the pause to deliver approvals whose export file
            # could not be written earlier.
            self._deliver()
            return False
        job_id, document_id, sha256 = claimed
        try:
            result = self._process(document_id, sha256)
            self._record_result(job_id, document_id, result)
        except Exception as error:
            # A result that cannot be written is a failed attempt like any other: it is
            # recorded with its own error instead of waiting for the lease to run out.
            self._record_failure(job_id, document_id, error)
            return True
        self._deliver()
        return True

    def _deliver(self) -> None:
        documents.deliver_exports(self.sessions, self.settings.export_dir, now=self.clock())

    def _claim(self) -> tuple[int, int, str] | None:
        now = self.clock()
        with transaction(self.sessions) as session:
            for buried in queue.bury_exhausted(session, now=now):
                document = documents.locked(session, buried.document_id)
                if document is not None and document.status in (QUEUED, PROCESSING):
                    documents.mark_failed(
                        session, document, buried.last_error or "abandoned", now=now
                    )
            while True:
                job = queue.claim(session, self.worker_id, now=now, lease_seconds=self.lease_s)
                if job is None:
                    return None
                document = documents.locked(session, job.document_id)
                if document is not None and document.status in (QUEUED, PROCESSING):
                    document.status = PROCESSING
                    return job.id, document.id, document.sha256
                # Decided, or gone, since the job was queued: there is nothing to read,
                # and the document is left as it is.
                queue.complete(session, job, now=now)

    def _process(self, document_id: int, sha256: str) -> Result:
        path: Path = documents.path_of(self.settings.storage_dir, sha256)
        pdf = path.read_bytes()
        result = self.pipeline.process(
            pdf,
            ledger=SessionLedger(self.sessions, document_id),
            today=self.settings.today or self.clock().date(),
            label=str(document_id),
        )
        outages = [
            attempt.error for attempt in result.attempts if attempt.error in _TRANSIENT_ERRORS
        ]
        if outages and result.outcome != "approved":
            # A reading is missing for a reason that says nothing about the document:
            # sending it to a person now would hide the outage behind another reason.
            raise TransientFailure(f"model server: {outages[-1]}")
        return result

    def _record_result(self, job_id: int, document_id: int, result: Result) -> None:
        now = self.clock()
        with transaction(self.sessions) as session:
            job = session.get(Job, job_id, with_for_update=True, populate_existing=True)
            if job is None or job.locked_by != self.worker_id:
                # The lease expired and another worker took the job over: its result is
                # the one that counts.
                logger.warning("lease_lost", extra={"job": job_id, "document": document_id})
                return
            document = documents.locked(session, document_id)
            if document is None or document.status != PROCESSING:
                queue.complete(session, job, now=now)
                logger.warning("result_dropped", extra={"job": job_id, "document": document_id})
                return
            documents.save_result(session, document, result, self.pipeline.master, now=now)
            queue.complete(session, job, now=now)
            outcome = document.status
        metrics.observe_result(result, outcome)
        logger.info(
            "document_processed",
            extra={
                "document": document_id,
                "outcome": outcome,
                "reasons": result.reasons,
                "tiers": [attempt.tier for attempt in result.attempts],
                "model_seconds": round(result.model_seconds, 2),
            },
        )

    def _record_failure(self, job_id: int, document_id: int, error: Exception) -> None:
        now = self.clock()
        message = f"{type(error).__name__}: {error}"
        with transaction(self.sessions) as session:
            job = session.get(Job, job_id, with_for_update=True, populate_existing=True)
            if job is None or job.locked_by != self.worker_id:
                return
            document = documents.locked(session, document_id)
            retry = queue.fail(
                session,
                job,
                message,
                now=now,
                backoff_seconds=self.settings.job_backoff_s,
                # A value the database refuses will be refused again: reading the
                # document once more would only cost the model calls.
                retry=not isinstance(error, DataError),
            )
            if document is not None and document.status == PROCESSING:
                if retry:
                    document.status = QUEUED
                else:
                    documents.mark_failed(session, document, message, now=now)
        metrics.JOB_FAILURES.labels(final=str(not retry).lower()).inc()
        log = logger.warning if isinstance(error, TransientFailure) else logger.exception
        log("job_failed", extra={"document": document_id, "retry": retry, "error": message})

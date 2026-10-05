"""What happens to a document in the database: intake, result, decision, export.

Every state change is written together with its audit event, in the caller's
transaction. The caller holds the row of the document (`locked`) while it decides, so
two decisions on one document cannot both go through. Approval also writes the outbox
row the accounting system reads, in the same transaction: a document is never approved
without being exported. The file itself is written by `deliver_exports`, which only
sees approvals that are committed: nothing is exported without being approved.
"""

import json
from contextlib import suppress
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from countersign.domain.schema import Invoice
from countersign.master import MasterData
from countersign.obs.logging import get_logger
from countersign.parsing.pdf import sha256_of
from countersign.pipeline.process import Result
from countersign.store import queue
from countersign.store.db import SessionFactory, transaction
from countersign.store.models import (
    APPROVED,
    DUPLICATE,
    FAILED,
    PROCESSING,
    QUEUED,
    REJECTED,
    REVIEW,
    Document,
    Event,
    Export,
)
from countersign.verify.checks import Prior

logger = get_logger(__name__)

SYSTEM = "system"


class AlreadyApproved(Exception):
    """Another document with this supplier and invoice number is already approved."""


class DatabaseLedger:
    """Duplicate detection against the documents already taken in.

    A document that a person refused counts too, after those taken in or waiting: the
    same invoice sent again must not undo that decision unseen.
    """

    def __init__(self, session: Session, document_id: int) -> None:
        self._session = session
        self._document_id = document_id

    def find(self, vendor_id: str, invoice_number: str) -> Prior | None:
        refused_by_a_person = and_(Document.status == REJECTED, Document.decided_by != SYSTEM)
        earlier = self._session.execute(
            select(
                Document.id,
                Document.status,
                Document.document_type,
                Document.total_gross,
                Document.issue_date,
                Document.decided_by,
            )
            .where(
                Document.vendor_id == vendor_id,
                Document.invoice_number == invoice_number,
                Document.id != self._document_id,
                or_(Document.status.in_((APPROVED, REVIEW)), refused_by_a_person),
            )
            .order_by(case((Document.status == REJECTED, 1), else_=0), Document.id)
            .limit(1)
        ).first()
        if earlier is None:
            return None
        return Prior(
            str(earlier.id),
            earlier.document_type,
            earlier.total_gross,
            issue_date=earlier.issue_date,
            rejected_by=earlier.decided_by if earlier.status == REJECTED else None,
        )


class SessionLedger:
    """Duplicate lookup that opens a short transaction for each question."""

    def __init__(self, sessions: SessionFactory, document_id: int) -> None:
        self._sessions = sessions
        self._document_id = document_id

    def find(self, vendor_id: str, invoice_number: str) -> Prior | None:
        with transaction(self._sessions) as session:
            return DatabaseLedger(session, self._document_id).find(vendor_id, invoice_number)


def locked(session: Session, document_id: int) -> Document | None:
    """The document, read again and held until the transaction ends.

    Whoever changes the state of a document starts here: the status it then checks
    cannot change under it (SELECT ... FOR UPDATE; on SQLite the transaction already
    holds the write lock).
    """
    return session.get(Document, document_id, with_for_update=True, populate_existing=True)


def add_event(
    session: Session, document: Document, actor: str, action: str, now: datetime, **detail: Any
) -> None:
    session.add(Event(document_id=document.id, at=now, actor=actor, action=action, detail=detail))


def path_of(storage_dir: Path, sha256: str) -> Path:
    return storage_dir / f"{sha256}.pdf"


def _store(storage_dir: Path, digest: str, data: bytes) -> None:
    """Write the file under its hash, whole or not at all: a worker never reads half."""
    target = path_of(storage_dir, digest)
    if target.is_file() and target.stat().st_size == len(data):
        return
    storage_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{digest}.{uuid4().hex}.tmp")
    temporary.write_bytes(data)
    temporary.replace(target)


def receive(
    session: Session,
    storage_dir: Path,
    data: bytes,
    *,
    filename: str,
    source: str,
    actor: str,
    now: datetime,
    max_attempts: int = 3,
) -> tuple[Document, bool]:
    """Store a file and queue it. Returns the document and whether it is new.

    The content hash is the idempotency key: a client that retries an upload, or two
    people who forward the same e-mail, get the same document back.

    The file is not opened here: reading an untrusted PDF is the worker's job, and the
    worker records the page count with its result.
    """
    digest = sha256_of(data)
    existing = session.scalar(select(Document).where(Document.sha256 == digest))
    if existing is not None:
        return existing, False

    _store(storage_dir, digest, data)
    document = Document(
        sha256=digest,
        filename=filename[:255] or f"{digest[:12]}.pdf",
        size_bytes=len(data),
        source=source,
        received_at=now,
        status=QUEUED,
    )
    try:
        with session.begin_nested():
            session.add(document)
            session.flush()
    except IntegrityError:
        # Two uploads of the same file raced: the other one created the row.
        existing = session.scalar(select(Document).where(Document.sha256 == digest))
        if existing is None:
            raise
        return existing, False
    queue.enqueue(session, document.id, now=now, max_attempts=max_attempts)
    add_event(session, document, actor, "received", now, filename=document.filename, source=source)
    return document, True


def requeue(
    session: Session, document: Document, *, actor: str, now: datetime, max_attempts: int
) -> None:
    """Queue a failed document, or one in review, to be read again.

    `document` must come from `locked`: a second request finds it queued and is
    refused, so a document never has two jobs.
    """
    if document.status not in (FAILED, REVIEW):
        raise ValueError(f"a document that is {document.status} cannot be reprocessed")
    document.status, document.error = QUEUED, None
    queue.enqueue(session, document.id, now=now, max_attempts=max_attempts)
    add_event(session, document, actor, "requeued", now)


def _copy_invoice(document: Document, invoice: Invoice | None) -> None:
    document.invoice = invoice.model_dump(mode="json") if invoice else None
    for field in (
        "invoice_number",
        "document_type",
        "issue_date",
        "due_date",
        "currency",
        "total_net",
        "total_tax",
        "total_gross",
    ):
        setattr(document, field, getattr(invoice, field) if invoice else None)


def _money(value: str | None) -> str | None:
    """An amount with its two decimals: "1521.9" was read from "1 521,90"."""
    if value is None:
        return None
    amount = Decimal(value)
    cents = amount.quantize(Decimal("0.01"))
    return str(cents) if cents == amount else value


def export_payload(document: Document, master: MasterData) -> dict[str, Any]:
    """What the accounting system needs to post and pay an approved document."""
    vendor = master.vendor(document.vendor_id) if document.vendor_id else None
    invoice = document.invoice or {}
    due_date = invoice.get("due_date")
    if due_date is None and vendor and document.issue_date:
        # No due date printed: the supplier's payment term on file applies.
        due_date = (document.issue_date + timedelta(days=vendor.payment_terms_days)).isoformat()
    return {
        "document_id": document.id,
        "sha256": document.sha256,
        "document_type": document.document_type,
        "vendor_id": document.vendor_id,
        "vendor_name": vendor.name if vendor else None,
        "invoice_number": document.invoice_number,
        "issue_date": invoice.get("issue_date"),
        "due_date": due_date,
        "currency": document.currency,
        "total_net": _money(invoice.get("total_net")),
        "total_tax": _money(invoice.get("total_tax")),
        "total_gross": _money(invoice.get("total_gross")),
        "po_number": invoice.get("po_number"),
        "lines": invoice.get("lines", []),
        # Payment goes to the account on file, never to the one printed on the document.
        "pay_to_iban": vendor.iban if vendor else None,
        "approved_by": document.decided_by,
        "approved_at": document.decided_at.isoformat() if document.decided_at else None,
    }


def _approve(
    session: Session, document: Document, master: MasterData, actor: str, now: datetime
) -> None:
    """Mark as approved and write the outbox row; the unique index arbitrates races."""
    if session.scalar(select(Export.id).where(Export.document_id == document.id)) is not None:
        raise ValueError(f"document {document.id} has already been exported")
    try:
        # The savepoint keeps a refused approval from spoiling the caller's transaction.
        # Only the status changes inside it, so the one constraint that can speak is the
        # index on (supplier, invoice number) of approved documents.
        with session.begin_nested():
            document.status, document.decided_by, document.decided_at = APPROVED, actor, now
            session.flush()
    except IntegrityError as error:
        raise AlreadyApproved(
            f"invoice {document.invoice_number} of supplier {document.vendor_id} "
            "is already approved"
        ) from error
    payload = export_payload(document, master)
    session.add(Export(document_id=document.id, payload=payload, created_at=now))
    session.flush()


def save_result(
    session: Session, document: Document, result: Result, master: MasterData, *, now: datetime
) -> None:
    """Record what the pipeline did and apply its decision."""
    kept = result.kept
    document.result = result.model_dump(mode="json")
    document.mode = result.mode
    document.kept_tier = kept.tier if kept else None
    document.vendor_id = result.vendor_id
    document.reasons = list(result.reasons)
    document.note, document.error = result.note, result.error
    document.model_seconds = round(result.model_seconds, 3)
    document.prompt_tokens, document.output_tokens = result.prompt_tokens, result.output_tokens
    document.page_count = result.page_count or document.page_count
    _copy_invoice(document, result.invoice)

    if result.outcome == APPROVED:
        try:
            _approve(session, document, master, SYSTEM, now)
        except AlreadyApproved:
            # Another document with this number was approved while this one was being
            # read. An exact copy is set aside; anything else is for a person to sort out.
            winner = session.execute(
                select(Document.document_type, Document.total_gross).where(
                    Document.vendor_id == document.vendor_id,
                    Document.invoice_number == document.invoice_number,
                    Document.status == APPROVED,
                    Document.id != document.id,
                )
            ).first()
            exact_copy = (
                winner is not None
                and winner.document_type == document.document_type
                and winner.total_gross == document.total_gross
            )
            document.reasons = ["duplicate"]
            if exact_copy:
                document.status = DUPLICATE
                document.decided_by, document.decided_at = SYSTEM, now
            else:
                document.status = REVIEW
                document.decided_by = document.decided_at = None
    else:
        document.status = result.outcome
        document.decided_by = SYSTEM if result.outcome in (REJECTED, DUPLICATE) else None
        document.decided_at = now if document.decided_by else None
    add_event(
        session,
        document,
        SYSTEM,
        "processed",
        now,
        outcome=document.status,
        reasons=document.reasons,
        tiers=[attempt.tier for attempt in result.attempts],
    )


def mark_failed(session: Session, document: Document, error: str, *, now: datetime) -> None:
    document.status, document.error = FAILED, error[:2000]
    add_event(session, document, SYSTEM, "failed", now, error=error[:500])


def decide(
    session: Session,
    document: Document,
    master: MasterData,
    *,
    action: str,
    reviewer: str,
    now: datetime,
    invoice: Invoice | None = None,
    vendor_id: str | None = None,
    overridden: list[str] | None = None,
    comment: str = "",
) -> None:
    """Apply a reviewer's decision on a document waiting for review.

    `document` must come from `locked`, in this transaction.
    """
    if document.status != REVIEW:
        raise ValueError(f"document {document.id} is not waiting for review ({document.status})")
    before = document.invoice
    if action == "approve":
        if invoice is not None:
            _copy_invoice(document, invoice)
        if vendor_id is not None:
            document.vendor_id = vendor_id
        _approve(session, document, master, reviewer, now)
    elif action == "reject":
        document.status, document.decided_by, document.decided_at = REJECTED, reviewer, now
    else:
        raise ValueError(f"unknown action: {action}")
    add_event(
        session,
        document,
        reviewer,
        "approved" if action == "approve" else "rejected",
        now,
        comment=comment,
        corrected=sorted(_changed(before, document.invoice)) if action == "approve" else [],
        overridden_checks=overridden or [],
    )


def _changed(before: dict[str, Any] | None, after: dict[str, Any] | None) -> set[str]:
    before, after = before or {}, after or {}
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}


def deliver_exports(sessions: SessionFactory, export_dir: Path, *, now: datetime) -> int:
    """Write pending outbox rows as one JSON file per document; return how many.

    Called after the approving transaction has committed, never inside it: only the
    rows of committed approvals are seen, so no file exists for a document that is not
    approved. The file is written first and its row marked afterwards; a crash in
    between delivers the row again, and since the file name is the document id, onto
    the same file.

    A file that cannot be written (disk full, directory gone) stops the delivery and
    leaves its row pending for the next call.
    """
    with transaction(sessions) as session:
        pending = [
            (export.id, export.document_id, export.payload)
            for export in session.scalars(
                select(Export).where(Export.delivered_at.is_(None)).order_by(Export.id)
            )
        ]
    written = []
    for export_id, document_id, payload in pending:
        target = export_dir / f"document-{document_id:08d}.json"
        temporary = target.with_name(f"{target.stem}.{uuid4().hex}.tmp")
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(target)
        except OSError:
            logger.exception("export_delivery_failed", extra={"document": document_id})
            with suppress(OSError):
                temporary.unlink()
            break
        written.append(export_id)
    if written:
        with transaction(sessions) as session:
            session.execute(
                update(Export)
                .where(Export.id.in_(written), Export.delivered_at.is_(None))
                .values(delivered_at=now)
            )
    return len(written)


def statistics(session: Session) -> dict[str, Any]:
    by_status = dict.fromkeys(
        (QUEUED, PROCESSING, APPROVED, REVIEW, REJECTED, DUPLICATE, FAILED), 0
    )
    for status, count in session.execute(
        select(Document.status, func.count()).group_by(Document.status)
    ):
        by_status[status] = count
    automatic = session.scalar(
        select(func.count()).where(Document.status == APPROVED, Document.decided_by == SYSTEM)
    )
    by_reviewer = session.scalar(
        select(func.count()).where(Document.status == APPROVED, Document.decided_by != SYSTEM)
    )
    processed = sum(by_status[status] for status in (APPROVED, REVIEW, REJECTED, DUPLICATE))
    seconds, prompt_tokens, output_tokens = session.execute(
        select(
            func.avg(Document.model_seconds),
            func.sum(Document.prompt_tokens),
            func.sum(Document.output_tokens),
        ).where(Document.result.is_not(None))
    ).one()
    tiers = dict(
        session.execute(
            select(Document.kept_tier, func.count())
            .where(Document.kept_tier.is_not(None))
            .group_by(Document.kept_tier)
        ).all()
    )
    reasons: dict[str, int] = {}
    for (document_reasons,) in session.execute(
        select(Document.reasons).where(Document.status == REVIEW)
    ):
        for reason in document_reasons or []:
            reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "by_status": by_status,
        "processed": processed,
        "approved_automatically": automatic or 0,
        "approved_by_reviewer": by_reviewer or 0,
        "automation_rate": round((automatic or 0) / processed, 4) if processed else None,
        "mean_model_seconds": round(float(seconds), 2) if seconds is not None else None,
        "prompt_tokens": int(prompt_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "kept_tier": tiers,
        "review_reasons": dict(sorted(reasons.items(), key=lambda item: -item[1])),
        "exports_pending": session.scalar(select(func.count()).where(Export.delivered_at.is_(None)))
        or 0,
    }

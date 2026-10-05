"""Tables.

`documents` is the record of what came in and what was decided; `jobs` is the work
queue; `events` is the audit trail; `exports` is the outbox read by the accounting
system. Types are limited to what SQLite and PostgreSQL share.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, TypeDecorator

# A document is in exactly one of these states.
QUEUED, PROCESSING = "queued", "processing"
APPROVED, REVIEW, REJECTED, DUPLICATE, FAILED = (
    "approved",
    "review",
    "rejected",
    "duplicate",
    "failed",
)
STATUSES = (QUEUED, PROCESSING, APPROVED, REVIEW, REJECTED, DUPLICATE, FAILED)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite drops the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: use an aware UTC datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcDateTime, dict[str, Any]: JSON, list[str]: JSON}  # noqa: RUF012


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Content hash: uploading the same file twice gives the same document.
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int]
    page_count: Mapped[int] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(32), default="api")
    received_at: Mapped[datetime] = mapped_column(default=utcnow)

    status: Mapped[str] = mapped_column(String(16), default=QUEUED, index=True)
    reasons: Mapped[list[str]] = mapped_column(default=list)
    note: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    # "system" for an automatic decision, else the reviewer's name.
    decided_by: Mapped[str | None] = mapped_column(String(64))

    # Copied from the kept extraction, for lists, search and duplicate detection.
    vendor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    document_type: Mapped[str | None] = mapped_column(String(16))
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    currency: Mapped[str | None] = mapped_column(String(3))
    total_net: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_gross: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # The invoice as approved (after corrections, if a reviewer made any).
    invoice: Mapped[dict[str, Any] | None]
    # Everything the pipeline did: attempts, raw extractions, checks. The audit record.
    result: Mapped[dict[str, Any] | None]
    mode: Mapped[str | None] = mapped_column(String(16))
    kept_tier: Mapped[str | None] = mapped_column(String(32))
    model_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)

    __table_args__ = (
        # The database, not the application, guarantees that a supplier's invoice number
        # is approved once: two workers racing on two copies cannot both win.
        Index(
            "uq_documents_approved_invoice",
            "vendor_id",
            "invoice_number",
            unique=True,
            sqlite_where=text("status = 'approved' AND invoice_number IS NOT NULL"),
            postgresql_where=text("status = 'approved' AND invoice_number IS NOT NULL"),
        ),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # queued -> running -> done | failed; a failed attempt goes back to queued until
    # max_attempts is reached.
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    run_after: Mapped[datetime] = mapped_column(default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_until: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]

    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)


class Event(Base):
    """Append-only audit trail: who did what to a document, and when."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(default=utcnow)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Export(Base):
    """Outbox: one row per approved document, written in the approval transaction."""

    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    delivered_at: Mapped[datetime | None]

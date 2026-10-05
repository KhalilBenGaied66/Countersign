"""Request and response bodies of the HTTP API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from countersign.domain.schema import Invoice
from countersign.store.models import Document, Event
from countersign.verify.checks import Check

# What the columns of `documents` hold, and what date and decimal arithmetic can take.
_REFERENCE_LENGTH = 64
_TEXT_LENGTH = 300
_AMOUNT_LIMIT = Decimal(10) ** 12
_DECIMAL_PLACES = 9
_FIRST_YEAR, _LAST_YEAR = 1990, 2100
_MAX_LINES = 500


class SubmittedInvoice(Invoice):
    """An invoice as typed by a reviewer: the same fields, within what can be stored.

    A value outside these bounds is refused when the request is read (422). Past this
    point it would only fail later, in a computation or in the database.
    """

    @model_validator(mode="after")
    def _within_bounds(self) -> "SubmittedInvoice":
        problems: list[str] = []

        def text(field: str, value: str | None, limit: int) -> None:
            if value is not None and len(value) > limit:
                problems.append(f"{field}: longer than {limit} characters")

        def amount(field: str, value: Decimal | None) -> None:
            if value is None:
                return
            exponent = value.as_tuple().exponent
            too_fine = isinstance(exponent, int) and exponent < -_DECIMAL_PLACES
            if abs(value) >= _AMOUNT_LIMIT or too_fine:
                problems.append(f"{field}: not an amount this system can hold")

        def day(field: str, value: date | None) -> None:
            if value is not None and not _FIRST_YEAR <= value.year <= _LAST_YEAR:
                problems.append(f"{field}: year outside {_FIRST_YEAR}-{_LAST_YEAR}")

        for field in ("invoice_number", "po_number", "referenced_invoice"):
            text(field, getattr(self, field), _REFERENCE_LENGTH)
        for field in ("supplier_vat_id", "supplier_siret", "supplier_iban", "currency"):
            text(field, getattr(self, field), _REFERENCE_LENGTH)
        text("supplier_name", self.supplier_name, _TEXT_LENGTH)
        for field in ("allowance_total", "charge_total", "total_net", "total_tax", "total_gross"):
            amount(field, getattr(self, field))
        day("issue_date", self.issue_date)
        day("due_date", self.due_date)
        if len(self.lines) > _MAX_LINES or len(self.vat_breakdown) > _MAX_LINES:
            problems.append(f"more than {_MAX_LINES} lines")
        for index, line in enumerate(self.lines[:_MAX_LINES]):
            text(f"lines[{index}].description", line.description, _TEXT_LENGTH)
            for field in ("quantity", "unit_price", "amount", "vat_rate"):
                amount(f"lines[{index}].{field}", getattr(line, field))
        for index, row in enumerate(self.vat_breakdown[:_MAX_LINES]):
            for field in ("rate", "base", "tax"):
                amount(f"vat_breakdown[{index}].{field}", getattr(row, field))
        if problems:
            raise ValueError("; ".join(problems))
        return self


class DocumentSummary(BaseModel):
    id: int
    filename: str
    status: str
    reasons: list[str]
    received_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    vendor_id: str | None
    vendor_name: str | None
    invoice_number: str | None
    document_type: str | None
    issue_date: date | None
    currency: str | None
    total_gross: Decimal | None
    mode: str | None
    kept_tier: str | None
    model_seconds: float

    @classmethod
    def of(cls, document: Document, vendor_name: str | None) -> "DocumentSummary":
        return cls(
            id=document.id,
            filename=document.filename,
            status=document.status,
            reasons=document.reasons or [],
            received_at=document.received_at,
            decided_at=document.decided_at,
            decided_by=document.decided_by,
            vendor_id=document.vendor_id,
            vendor_name=vendor_name,
            invoice_number=document.invoice_number,
            document_type=document.document_type,
            issue_date=document.issue_date,
            currency=document.currency,
            total_gross=document.total_gross,
            mode=document.mode,
            kept_tier=document.kept_tier,
            model_seconds=document.model_seconds,
        )


class EventView(BaseModel):
    at: datetime
    actor: str
    action: str
    detail: dict[str, Any]

    @classmethod
    def of(cls, event: Event) -> "EventView":
        return cls(at=event.at, actor=event.actor, action=event.action, detail=event.detail)


class AttemptView(BaseModel):
    tier: str
    mode: str
    model: str | None
    prompt_id: str | None
    error: str | None
    prompt_tokens: int
    output_tokens: int
    duration_s: float
    checks: list[Check]
    kept: bool


class DocumentDetail(DocumentSummary):
    sha256: str
    size_bytes: int
    page_count: int
    note: str | None
    error: str | None
    invoice: Invoice | None
    checks: list[Check]
    attempts: list[AttemptView]
    events: list[EventView]
    prompt_tokens: int
    output_tokens: int


class DocumentPage(BaseModel):
    total: int
    items: list[DocumentSummary]


class Received(BaseModel):
    document: DocumentSummary
    # False when this exact file had already been received.
    created: bool


class RecheckRequest(BaseModel):
    invoice: SubmittedInvoice


class RecheckResponse(BaseModel):
    checks: list[Check]
    vendor_id: str | None
    vendor_name: str | None


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    # The invoice as corrected by the reviewer; omitted to approve it as extracted.
    invoice: SubmittedInvoice | None = None
    comment: str = Field(default="", max_length=2000)
    # Ids of the failed checks the reviewer was shown and approves despite. A check
    # that fails and is not listed here was never seen: the approval is refused.
    acknowledged: list[str] = Field(default_factory=list, max_length=200)


class VendorView(BaseModel):
    vendor_id: str
    name: str
    country: str
    currency: str
    vat_id: str | None
    iban: str | None
    po_required: bool


class Readiness(BaseModel):
    ready: bool
    database: bool
    models: dict[str, bool]
    replay: bool

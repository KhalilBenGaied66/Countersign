"""HTTP API.

Handlers are thin: they translate between HTTP and the functions of
`countersign.store.documents`, and map domain errors to status codes. A request was
authenticated before its body was read (`countersign.api.guard`); roles are enforced
here.

A handler opens its own transaction and commits it before it answers, so that what a
client is told has happened. Whatever changes the state of a document reads the
document again under a lock, inside that transaction: of two decisions on one
document, the second sees the first.
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session

from countersign.api.context import Context
from countersign.api.guard import Principal
from countersign.api.schemas import (
    AttemptView,
    Decision,
    DocumentDetail,
    DocumentPage,
    DocumentSummary,
    EventView,
    Readiness,
    Received,
    RecheckRequest,
    RecheckResponse,
    VendorView,
)
from countersign.domain.schema import Invoice
from countersign.obs import metrics
from countersign.parsing.pdf import UnreadableDocument, render_page
from countersign.pipeline.process import Attempt
from countersign.store import documents, queue
from countersign.store.db import transaction
from countersign.store.models import REVIEW, STATUSES, Document, Event
from countersign.verify.checks import Check, Ledger, blocking_failures

api = APIRouter()
probes = APIRouter()

_ROLE_RANK = {"operator": 1, "reviewer": 2}

# Identifiers are 32-bit in the database: a larger number is not a document.
DocumentId = Annotated[int, Path(ge=1, le=2**31 - 1)]


def get_context(request: Request) -> Context:
    context: Context = request.app.state.context
    return context


ContextDep = Annotated[Context, Depends(get_context)]


def principal_of(request: Request) -> Principal:
    """Who the guard recognised; without the guard in front, nobody."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="missing or unknown API key")
    return principal


def require(role: str) -> Any:
    def check(principal: Annotated[Principal, Depends(principal_of)]) -> Principal:
        if _ROLE_RANK.get(principal.role, 0) < _ROLE_RANK[role]:
            raise HTTPException(status_code=403, detail=f"this action needs the '{role}' role")
        return principal

    return Depends(check)


def _vendor_name(context: Context, vendor_id: str | None) -> str | None:
    vendor = context.master.vendor(vendor_id) if vendor_id else None
    return vendor.name if vendor else None


def _summary(context: Context, document: Document) -> DocumentSummary:
    return DocumentSummary.of(document, _vendor_name(context, document.vendor_id))


def _load(session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="no such document")
    return document


def _locked(session: Session, document_id: int) -> Document:
    document = documents.locked(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="no such document")
    return document


def _read_file(context: Context, sha256: str) -> bytes:
    path = documents.path_of(context.settings.storage_dir, sha256)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="the file of this document is no longer stored")
    return path.read_bytes()


# ----------------------------------------------------------------------------- documents


@api.post("/documents", response_model=Received, status_code=201)
def upload_document(
    response: Response,
    context: ContextDep,
    file: Annotated[UploadFile, File(description="A PDF invoice")],
    principal: Principal = require("operator"),
) -> Received:
    """Receive a PDF and queue it. Sending the same file again returns the same document.

    The file is stored, not opened: reading it is the worker's job.
    """
    limit = context.settings.max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"file larger than {limit // (1024 * 1024)} MB")
    if not data.lstrip()[:5] == b"%PDF-":
        raise HTTPException(status_code=415, detail="only PDF files are accepted")
    with transaction(context.sessions) as session:
        document, created = documents.receive(
            session,
            context.settings.storage_dir,
            data,
            filename=file.filename or "",
            source="api",
            actor=principal.name,
            now=context.clock(),
            max_attempts=context.settings.job_max_attempts,
        )
        received = Received(document=_summary(context, document), created=created)
    if not created:
        response.status_code = 200
    return received


@api.get("/documents", response_model=DocumentPage)
def list_documents(
    context: ContextDep,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="File, invoice number or supplier")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
    _: Principal = require("operator"),
) -> DocumentPage:
    query = select(Document)
    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=422, detail=f"unknown status: {status}")
        query = query.where(Document.status == status)
    if q:
        needle = q.strip().lower()
        pattern = f"%{needle}%"
        vendor_ids = [v.vendor_id for v in context.master.vendors if needle in v.name.lower()]
        query = query.where(
            or_(
                func.lower(Document.filename).like(pattern),
                func.lower(Document.invoice_number).like(pattern),
                Document.vendor_id.in_(vendor_ids),
            )
        )
    with transaction(context.sessions) as session:
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.scalars(query.order_by(Document.id.desc()).limit(limit).offset(offset))
        return DocumentPage(total=total, items=[_summary(context, document) for document in rows])


@api.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: DocumentId, context: ContextDep, _: Principal = require("operator")
) -> DocumentDetail:
    with transaction(context.sessions) as session:
        document = _load(session, document_id)
        result = document.result or {}
        final = result.get("final")
        attempts = [
            AttemptView(
                **Attempt.model_validate(attempt).model_dump(
                    include={
                        "tier",
                        "mode",
                        "model",
                        "prompt_id",
                        "error",
                        "prompt_tokens",
                        "output_tokens",
                        "duration_s",
                        "checks",
                    }
                ),
                kept=index == final,
            )
            for index, attempt in enumerate(result.get("attempts", []))
        ]
        kept_checks: list[Check] = attempts[final].checks if final is not None else []
        events = session.scalars(
            select(Event).where(Event.document_id == document.id).order_by(Event.id)
        )
        return DocumentDetail(
            **_summary(context, document).model_dump(),
            sha256=document.sha256,
            size_bytes=document.size_bytes,
            page_count=document.page_count,
            note=document.note,
            error=document.error,
            invoice=Invoice.model_validate(document.invoice) if document.invoice else None,
            checks=kept_checks,
            attempts=attempts,
            events=[EventView.of(event) for event in events],
            prompt_tokens=document.prompt_tokens,
            output_tokens=document.output_tokens,
        )


def _stored(context: Context, document_id: int) -> tuple[str, str]:
    """Hash and name of a document's file, read in a transaction that ends here."""
    with transaction(context.sessions) as session:
        document = _load(session, document_id)
        return document.sha256, document.filename


@api.get("/documents/{document_id}/file")
def get_document_file(
    document_id: DocumentId, context: ContextDep, _: Principal = require("operator")
) -> FileResponse:
    sha256, filename = _stored(context, document_id)
    path = documents.path_of(context.settings.storage_dir, sha256)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="the file of this document is no longer stored")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline",
    )


@api.get("/documents/{document_id}/pages/{number}")
def get_document_page(
    document_id: DocumentId,
    number: Annotated[int, Path(ge=0, le=10_000)],
    context: ContextDep,
    _: Principal = require("operator"),
) -> Response:
    """One page of the document as an image, rendered on the server."""
    sha256, _name = _stored(context, document_id)
    try:
        image = render_page(_read_file(context, sha256), number)
    except UnreadableDocument as error:
        raise HTTPException(status_code=422, detail=f"the file cannot be read: {error}") from error
    if image is None:
        raise HTTPException(status_code=404, detail="no such page")
    # A stored file never changes: the rendering can be kept by the browser.
    headers = {"Cache-Control": "private, max-age=86400, immutable"}
    return Response(content=image, media_type="image/png", headers=headers)


def _recheck(context: Context, sha256: str, invoice: Invoice, ledger: Ledger) -> Attempt:
    return context.pipeline.recheck(
        _read_file(context, sha256), invoice, ledger=ledger, today=context.today()
    )


@api.post("/documents/{document_id}/recheck", response_model=RecheckResponse)
def recheck_document(
    document_id: DocumentId,
    body: RecheckRequest,
    context: ContextDep,
    _: Principal = require("reviewer"),
) -> RecheckResponse:
    """Run the checks on an invoice as corrected by the reviewer. Nothing is saved."""
    sha256, _name = _stored(context, document_id)
    ledger = documents.SessionLedger(context.sessions, document_id)
    attempt = _recheck(context, sha256, body.invoice, ledger)
    return RecheckResponse(
        checks=attempt.checks,
        vendor_id=attempt.vendor_id,
        vendor_name=_vendor_name(context, attempt.vendor_id),
    )


@api.post("/documents/{document_id}/decision", response_model=DocumentSummary)
def decide_document(
    document_id: DocumentId,
    body: Decision,
    context: ContextDep,
    principal: Principal = require("reviewer"),
) -> DocumentSummary:
    """Approve or reject a document that is waiting for review.

    An approval names the failed checks the reviewer saw (`acknowledged`). The checks
    run again here, on what is approved; one that fails without having been shown
    refuses the approval instead of being overridden unseen.
    """
    now = context.clock()
    with transaction(context.sessions) as session:
        document = _locked(session, document_id)
        if document.status != REVIEW:
            raise HTTPException(
                status_code=409, detail=f"the document is not in review ({document.status})"
            )
        if body.action == "reject":
            documents.decide(
                session,
                document,
                context.master,
                action="reject",
                reviewer=principal.name,
                now=now,
                comment=body.comment,
            )
            return _summary(context, document)

        invoice = body.invoice or (
            Invoice.model_validate(document.invoice) if document.invoice else None
        )
        if invoice is None:
            raise HTTPException(
                status_code=422, detail="there is no invoice to approve: enter its fields"
            )
        if invoice.document_type == "other":
            raise HTTPException(
                status_code=422, detail="only an invoice or a credit note can be approved"
            )
        ledger = documents.DatabaseLedger(session, document.id)
        attempt = _recheck(context, document.sha256, invoice, ledger)
        if attempt.vendor_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "the supplier is not in the vendor master: "
                    "it must be created there before approval"
                ),
            )
        failures = [check.id for check in blocking_failures(attempt.checks)]
        if failures and not body.comment.strip():
            raise HTTPException(
                status_code=422,
                detail="a comment is required to approve despite: " + ", ".join(failures),
            )
        unseen = [check_id for check_id in failures if check_id not in body.acknowledged]
        if unseen:
            raise HTTPException(
                status_code=409,
                detail="checks that fail and were not acknowledged: " + ", ".join(unseen),
            )
        try:
            documents.decide(
                session,
                document,
                context.master,
                action="approve",
                reviewer=principal.name,
                now=now,
                invoice=attempt.invoice,
                vendor_id=attempt.vendor_id,
                overridden=failures,
                comment=body.comment,
            )
        except documents.AlreadyApproved as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DataError as error:
            raise HTTPException(
                status_code=422, detail="a value of this invoice cannot be stored"
            ) from error
        summary = _summary(context, document)
    # The approval is committed: only now may its file reach the accounting system.
    documents.deliver_exports(context.sessions, context.settings.export_dir, now=now)
    return summary


@api.post("/documents/{document_id}/reprocess", response_model=DocumentSummary, status_code=202)
def reprocess_document(
    document_id: DocumentId,
    context: ContextDep,
    principal: Principal = require("reviewer"),
) -> DocumentSummary:
    """Queue a document again, for instance after the model server came back."""
    with transaction(context.sessions) as session:
        document = _locked(session, document_id)
        try:
            documents.requeue(
                session,
                document,
                actor=principal.name,
                now=context.clock(),
                max_attempts=context.settings.job_max_attempts,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _summary(context, document)


# ------------------------------------------------------------------------------- others


@api.get("/stats")
def get_statistics(context: ContextDep, _: Principal = require("operator")) -> dict[str, Any]:
    with transaction(context.sessions) as session:
        statistics = documents.statistics(session)
        statistics["jobs"] = queue.depth(session)
    statistics["models"] = [tier.model for tier in context.pipeline.config.tiers]
    statistics["replay"] = context.settings.replay_dir is not None
    return statistics


@api.get("/vendors", response_model=list[VendorView])
def list_vendors(context: ContextDep, _: Principal = require("operator")) -> list[VendorView]:
    return [
        VendorView(**vendor.model_dump(include=set(VendorView.model_fields)))
        for vendor in context.master.vendors
    ]


@probes.get("/healthz", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@probes.get("/readyz", response_model=Readiness)
def readiness(context: ContextDep, response: Response) -> Readiness:
    """Whether a document submitted now can be processed: database and models reachable."""
    try:
        with transaction(context.sessions) as session:
            session.execute(text("SELECT 1"))
        database = True
    except SQLAlchemyError:
        database = False
    replay = context.ollama is None
    models = {
        tier.model: True if context.ollama is None else context.ollama.is_ready(tier.model)
        for tier in context.pipeline.config.tiers
    }
    ready = database and all(models.values())
    if not ready:
        response.status_code = 503
    return Readiness(ready=ready, database=database, models=models, replay=replay)


@probes.get("/metrics", include_in_schema=False)
def prometheus(context: ContextDep) -> Response:
    body = metrics.render() + metrics.render(context.registry)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

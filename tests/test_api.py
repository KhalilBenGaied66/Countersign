"""The HTTP API, from upload to a reviewer's decision."""

import inspect
import json
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from starlette.formparsers import MultiPartParser
from starlette.types import Message, Receive, Scope, Send

from countersign.api import routes
from countersign.api.app import WEB_DIR, create_app
from countersign.api.guard import MAX_JSON_BYTES
from countersign.config import Settings
from countersign.datagen.model import InvoiceData
from countersign.datagen.render import render_pdf
from countersign.llm.client import ModelError
from countersign.llm.prompts import DEFAULT_PROMPT
from countersign.store.db import transaction
from countersign.store.models import Export, Job
from countersign.worker import Worker
from tests.support import LARGE_MODEL, SMALL_MODEL, ScriptedModel, invoice_data, perfect_reply


class Harness:
    """An application around a scripted model, with a worker the test runs by hand."""

    def __init__(self, client: TestClient, model: ScriptedModel) -> None:
        self.client = client
        self.model = model
        self.context = client.app.state.context  # type: ignore[attr-defined]
        self.worker = Worker(
            sessions=self.context.sessions,
            pipeline=self.context.pipeline,
            settings=self.context.settings,
            worker_id="test-worker",
        )

    def upload(self, data: InvoiceData | bytes, name: str = "invoice.pdf", **options: Any) -> Any:
        pdf = data if isinstance(data, bytes) else render_pdf(data)
        return self.client.post(
            "/api/documents", files={"file": (name, pdf, "application/pdf")}, **options
        )

    def process(self) -> None:
        while self.worker.run_once():
            pass

    def submit(self, data: InvoiceData, reply: dict[str, Any] | None = None) -> int:
        """Upload a document, script the small model's answer for it, and process it."""
        self.model.replies[SMALL_MODEL] = perfect_reply(data) if reply is None else reply
        document_id: int = self.upload(data).json()["document"]["id"]
        self.process()
        return document_id

    def misread(self, data: InvoiceData) -> int:
        """A document both models misread: it ends up in review."""
        wrong = perfect_reply(data)
        wrong["total_gross"] += 100
        self.model.replies[LARGE_MODEL] = wrong
        return self.submit(data, wrong)

    def invoice(self, document_id: int) -> dict[str, Any]:
        invoice: dict[str, Any] = self.client.get(f"/api/documents/{document_id}").json()["invoice"]
        return invoice

    def failing(self, document_id: int, invoice: dict[str, Any] | None = None) -> list[str]:
        """Ids of the checks an invoice fails, as the console is shown them."""
        body = {"invoice": invoice or self.invoice(document_id)}
        checks = self.client.post(f"/api/documents/{document_id}/recheck", json=body).json()
        return [c["id"] for c in checks["checks"] if not c["passed"] and c["blocking"]]

    def count(self, table: type) -> int:
        with transaction(self.context.sessions) as session:
            return session.scalar(select(func.count()).select_from(table)) or 0


@pytest.fixture
def harness(settings: Settings) -> Iterator[Harness]:
    model = ScriptedModel({})
    with TestClient(create_app(settings, client=model, start_workers=False)) as client:
        yield Harness(client, model)


def together(*calls: Any) -> list[Any]:
    """Run the calls at the same moment, each in its thread; their results in order."""
    results: list[Any] = [None] * len(calls)
    start = threading.Barrier(len(calls))

    def run(index: int) -> None:
        start.wait()
        results[index] = calls[index]()

    threads = [threading.Thread(target=run, args=(index,)) for index in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


# ---------------------------------------------------------------------------- intake


def test_upload_queues_a_document(harness: Harness) -> None:
    response = harness.upload(invoice_data("forez"), name="facture mars.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["document"]["status"] == "queued"
    assert body["document"]["filename"] == "facture mars.pdf"


def test_uploading_the_same_file_again_returns_the_same_document(harness: Harness) -> None:
    data = invoice_data("forez")
    first = harness.upload(data).json()
    again = harness.upload(data, name="copy.pdf")
    assert again.status_code == 200
    assert again.json() == {"document": first["document"], "created": False}
    assert harness.client.get("/api/documents").json()["total"] == 1


def test_the_same_file_uploaded_several_times_at_once_is_one_document(harness: Harness) -> None:
    """On PostgreSQL the uploads really overlap: all but one lose on the unique hash
    and are answered with the document of the one that won."""
    pdf = render_pdf(invoice_data("forez"))
    responses = together(*[lambda: harness.upload(pdf) for _ in range(4)])
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    assert len({response.json()["document"]["id"] for response in responses}) == 1
    assert (harness.client.get("/api/documents").json()["total"], harness.count(Job)) == (1, 1)


def test_only_pdf_files_are_accepted(harness: Harness) -> None:
    response = harness.upload(b"PK\x03\x04 this is a zip", name="invoice.pdf")
    assert response.status_code == 415
    assert harness.client.post("/api/documents").status_code == 422


def test_an_oversized_upload_is_refused(settings: Settings) -> None:
    settings.max_upload_bytes = 1024
    with TestClient(create_app(settings, client=ScriptedModel({}), start_workers=False)) as client:
        response = client.post(
            "/api/documents", files={"file": ("big.pdf", b"%PDF-" + bytes(2048), "application/pdf")}
        )
    assert response.status_code == 413


def encrypted_pdf() -> bytes:
    """A one-page PDF whose trailer names an AES-256 /Encrypt dictionary."""
    encrypt = (
        b"<< /Filter /Standard /V 5 /R 6 /Length 256 /P -1 "
        b"/O <" + b"11" * 48 + b"> /U <" + b"22" * 48 + b"> "
        b"/OE <" + b"33" * 32 + b"> /UE <" + b"44" * 32 + b"> /Perms <" + b"55" * 16 + b"> "
        b"/CF << /StdCF << /CFM /AESV3 /AuthEvent /DocOpen /Length 32 >> >> "
        b"/StmF /StdCF /StrF /StdCF >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        encrypt,
    ]
    out, offsets = b"%PDF-1.7\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    identifier = b"<00112233445566778899aabbccddeeff>"
    out += b"trailer\n<< /Size 5 /Root 1 0 R /Encrypt 4 0 R /ID [" + identifier * 2 + b"] >>\n"
    return out + f"startxref\n{xref}\n%%EOF\n".encode()


def test_an_upload_is_stored_without_being_opened(harness: Harness) -> None:
    """An encrypted file used to crash the upload: now it is queued, and a worker says
    what is wrong with it."""
    assert not inspect.iscoroutinefunction(routes.upload_document)  # nothing blocks the loop
    response = harness.upload(encrypted_pdf(), name="protected.pdf")
    assert response.status_code == 201
    document = response.json()["document"]
    assert document["status"] == "queued"
    detail = harness.client.get(f"/api/documents/{document['id']}").json()
    assert detail["page_count"] == 0  # not known before a worker has read the file

    harness.process()
    detail = harness.client.get(f"/api/documents/{document['id']}").json()
    assert (detail["status"], detail["reasons"]) == ("review", ["unreadable"])


def test_a_request_is_committed_before_it_is_answered(settings: Settings) -> None:
    """What a client is told has happened: a 201 for a document that is not there yet,
    or a 200 for an approval that then fails to commit, must not exist."""
    order: list[str] = []
    model = ScriptedModel({})
    app = create_app(settings, client=model, start_workers=False)

    async def recording(scope: Scope, receive: Receive, send: Send) -> None:
        async def tracked(message: Message) -> None:
            if message["type"] == "http.response.start":
                order.append("answer")
            await send(message)

        await app(scope, receive, tracked)

    with TestClient(recording) as client:
        harness = Harness(TestClient(app), model)
        sqlalchemy_event.listen(
            harness.context.sessions, "after_commit", lambda _: order.append("commit")
        )
        data = invoice_data("forez")
        uploaded = client.post(
            "/api/documents", files={"file": ("a.pdf", render_pdf(data), "application/pdf")}
        )
        assert uploaded.status_code == 201
        assert order[0] == "commit"  # the savepoint of the upload reports one as well
        assert order[-1] == "answer"
        assert order.count("answer") == 1

        wrong = perfect_reply(data)
        wrong["total_gross"] += 100
        model.replies.update({SMALL_MODEL: wrong, LARGE_MODEL: wrong})
        harness.process()
        document_id = uploaded.json()["document"]["id"]
        invoice = harness.invoice(document_id)
        invoice["total_gross"] = str(data.gross)
        order.clear()
        decided = client.post(
            f"/api/documents/{document_id}/decision", json={"action": "approve", "invoice": invoice}
        )
        assert decided.status_code == 200
        assert order.count("answer") == 1
        assert order[-1] == "answer"
        assert order[0] == "commit"


# ------------------------------------------------------------------- reading results


def test_a_processed_document_shows_what_was_read_and_why_it_was_approved(harness: Harness) -> None:
    data = invoice_data("forez")
    document_id = harness.submit(data)
    detail = harness.client.get(f"/api/documents/{document_id}").json()

    assert detail["status"] == "approved"
    assert detail["decided_by"] == "system"
    assert detail["vendor_name"] == "Cartonnages du Forez SARL"
    assert detail["invoice"]["invoice_number"] == data.number
    assert detail["invoice"]["total_gross"] == str(data.gross)
    assert detail["page_count"] == 1
    assert detail["checks"]
    assert all(check["passed"] for check in detail["checks"])
    assert [(attempt["tier"], attempt["kept"]) for attempt in detail["attempts"]] == [
        ("small", True)
    ]
    assert detail["attempts"][0]["prompt_id"] == DEFAULT_PROMPT
    assert [event["action"] for event in detail["events"]] == ["received", "processed"]
    assert harness.client.get("/api/documents/9999").status_code == 404


def test_a_document_in_review_shows_both_attempts_and_the_failed_checks(harness: Harness) -> None:
    document_id = harness.misread(invoice_data("forez"))
    detail = harness.client.get(f"/api/documents/{document_id}").json()
    assert detail["status"] == "review"
    assert set(detail["reasons"]) == {"arithmetic", "grounding"}
    assert [(attempt["tier"], attempt["kept"]) for attempt in detail["attempts"]] == [
        ("small", False),
        ("large", True),
    ]
    failed = {check["id"] for check in detail["checks"] if not check["passed"]}
    assert failed == {"arithmetic.totals", "arithmetic.labelled", "grounding.header"}


def test_the_stored_file_is_served_inline(harness: Harness) -> None:
    data = invoice_data("forez")
    document_id = harness.upload(data).json()["document"]["id"]
    response = harness.client.get(f"/api/documents/{document_id}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == render_pdf(data)


def test_listing_filters_by_status_and_searches(harness: Harness) -> None:
    approved = harness.submit(invoice_data("forez"))
    review = harness.submit(invoice_data("fgs"))
    listing = harness.client.get("/api/documents").json()
    assert listing["total"] == 2
    assert [item["id"] for item in listing["items"]] == [review, approved]  # newest first

    def ids(query: str) -> list[int]:
        return [
            item["id"] for item in harness.client.get(f"/api/documents?{query}").json()["items"]
        ]

    assert ids("status=review") == [review]
    assert ids("status=approved") == [approved]
    assert ids("q=forez") == [approved]  # by supplier name
    assert ids("q=2603") == [approved]  # by invoice number
    assert ids("q=nothing-like-this") == []
    assert ids("limit=1") == [review]
    assert ids("limit=1&offset=1") == [approved]
    assert harness.client.get("/api/documents?status=bogus").status_code == 422
    assert harness.client.get("/api/documents?limit=0").status_code == 422


def test_numbers_no_database_holds_are_refused_instead_of_crashing(harness: Harness) -> None:
    huge = 10**20
    for path in (
        f"/api/documents?offset={huge}",
        f"/api/documents/{huge}",
        f"/api/documents/{huge}/file",
        f"/api/documents/{huge}/pages/1",
        f"/api/documents/1/pages/{huge}",
    ):
        assert harness.client.get(path).status_code == 422, path
    for path in (f"/api/documents/{huge}/reprocess", f"/api/documents/{huge}/decision"):
        assert harness.client.post(path, json={"action": "reject"}).status_code == 422, path


# ------------------------------------------------------------------------- reviewing


def corrected(harness: Harness, document_id: int, data: InvoiceData) -> dict[str, Any]:
    invoice = harness.invoice(document_id)
    invoice["total_gross"] = str(data.gross)
    return invoice


def test_rechecking_a_correction_saves_nothing(harness: Harness) -> None:
    data = invoice_data("forez")
    document_id = harness.misread(data)
    response = harness.client.post(
        f"/api/documents/{document_id}/recheck",
        json={"invoice": corrected(harness, document_id, data)},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(check["passed"] for check in body["checks"])
    assert body["vendor_name"] == "Cartonnages du Forez SARL"
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "review"


def test_a_reviewer_approves_a_corrected_invoice(harness: Harness, settings: Settings) -> None:
    data = invoice_data("forez")
    document_id = harness.misread(data)
    response = harness.client.post(
        f"/api/documents/{document_id}/decision",
        json={"action": "approve", "invoice": corrected(harness, document_id, data)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    detail = harness.client.get(f"/api/documents/{document_id}").json()
    assert detail["decided_by"] == "local"
    assert detail["invoice"]["total_gross"] == str(data.gross)
    assert detail["events"][-1]["action"] == "approved"
    assert detail["events"][-1]["detail"]["corrected"] == ["total_gross"]
    exported = json.loads(
        (settings.export_dir / f"document-{document_id:08d}.json").read_text("utf-8")
    )
    assert exported["total_gross"] == str(data.gross)


def test_approving_despite_a_failed_check_needs_a_comment_and_is_recorded(harness: Harness) -> None:
    document_id = harness.misread(invoice_data("forez"))
    url = f"/api/documents/{document_id}/decision"
    failing = harness.failing(document_id)
    assert set(failing) == {"arithmetic.totals", "arithmetic.labelled", "grounding.header"}

    refused = harness.client.post(url, json={"action": "approve", "acknowledged": failing})
    assert refused.status_code == 422
    assert "comment is required" in refused.json()["detail"]

    approval = {"action": "approve", "comment": "confirmed by phone", "acknowledged": failing}
    accepted = harness.client.post(url, json=approval)
    assert accepted.status_code == 200
    event = harness.client.get(f"/api/documents/{document_id}").json()["events"][-1]
    assert event["detail"]["comment"] == "confirmed by phone"
    assert set(event["detail"]["overridden_checks"]) == set(failing)


def test_a_comment_does_not_override_a_failed_check_the_reviewer_was_not_shown(
    harness: Harness,
) -> None:
    """The checks run again on what is approved: one that fails there, and is not among
    those the reviewer acknowledged, refuses the approval."""
    document_id = harness.misread(invoice_data("forez"))
    url = f"/api/documents/{document_id}/decision"
    failing = harness.failing(document_id)

    blind = harness.client.post(url, json={"action": "approve", "comment": "looks fine"})
    assert blind.status_code == 409
    assert all(check in blind.json()["detail"] for check in failing)

    seen, unseen = failing[:-1], failing[-1]
    partial = harness.client.post(
        url, json={"action": "approve", "comment": "looks fine", "acknowledged": seen}
    )
    assert partial.status_code == 409
    detail = partial.json()["detail"]
    assert unseen in detail
    assert not any(check in detail for check in seen)
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "review"
    assert harness.count(Export) == 0


def test_an_invoice_from_a_supplier_that_is_not_on_file_cannot_be_approved(
    harness: Harness,
) -> None:
    document_id = harness.submit(invoice_data("fgs"))
    response = harness.client.post(
        f"/api/documents/{document_id}/decision", json={"action": "approve", "comment": "please"}
    )
    assert response.status_code == 422
    assert "vendor master" in response.json()["detail"]


def test_a_reviewer_rejects(harness: Harness) -> None:
    document_id = harness.misread(invoice_data("forez"))
    response = harness.client.post(
        f"/api/documents/{document_id}/decision", json={"action": "reject", "comment": "not ours"}
    )
    assert response.json()["status"] == "rejected"
    again = harness.client.post(f"/api/documents/{document_id}/decision", json={"action": "reject"})
    assert again.status_code == 409


def test_a_decision_is_only_possible_on_a_document_in_review(harness: Harness) -> None:
    document_id = harness.submit(invoice_data("forez"))
    response = harness.client.post(
        f"/api/documents/{document_id}/decision", json={"action": "approve"}
    )
    assert response.status_code == 409
    assert (
        harness.client.post(
            f"/api/documents/{document_id}/decision", json={"action": "escalate"}
        ).status_code
        == 422
    )


def test_approving_a_number_that_is_already_approved_is_a_conflict(harness: Harness) -> None:
    first = invoice_data("forez")
    harness.submit(first)
    second = invoice_data("forez", seed=3, sequence=190)
    document_id = harness.misread(second)
    invoice = corrected(harness, document_id, second)
    invoice["invoice_number"] = first.number
    response = harness.client.post(
        f"/api/documents/{document_id}/decision",
        json={
            "action": "approve",
            "invoice": invoice,
            "comment": "same number",
            "acknowledged": harness.failing(document_id, invoice),
        },
    )
    assert response.status_code == 409
    assert "already approved" in response.json()["detail"]
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "review"


def test_two_decisions_at_the_same_moment_do_not_both_succeed(
    harness: Harness, settings: Settings
) -> None:
    """One reviewer approves while another rejects: the second one is told so, and the
    document is exported if and only if it ends approved."""
    for round_number in range(4):
        data = invoice_data("forez", seed=round_number + 1, sequence=200 + round_number)
        document_id = harness.misread(data)
        url = f"/api/documents/{document_id}/decision"
        approval = {"action": "approve", "invoice": corrected(harness, document_id, data)}
        rejection = {"action": "reject", "comment": "not ours"}
        approve, reject = together(
            lambda url=url, body=approval: harness.client.post(url, json=body),
            lambda url=url, body=rejection: harness.client.post(url, json=body),
        )
        assert sorted((approve.status_code, reject.status_code)) == [200, 409]
        winner = "approved" if approve.status_code == 200 else "rejected"
        detail = harness.client.get(f"/api/documents/{document_id}").json()
        assert detail["status"] == winner
        assert [event["action"] for event in detail["events"]][2:] == [winner]
        exported = (settings.export_dir / f"document-{document_id:08d}.json").exists()
        assert exported == (winner == "approved")
    with transaction(harness.context.sessions) as session:
        approved = harness.client.get("/api/documents?status=approved").json()["total"]
        assert session.scalar(select(func.count()).select_from(Export)) == approved


def test_values_typed_by_a_reviewer_that_cannot_be_stored_are_refused(harness: Harness) -> None:
    data = invoice_data("forez")
    document_id = harness.misread(data)
    good = corrected(harness, document_id, data)
    line = good["lines"][0]
    for change in (
        {"invoice_number": "REF-" + "7" * 66},
        {"total_gross": "73282932000074"},
        {"total_gross": "1E+400"},
        {"total_net": "0." + "0" * 20 + "1"},
        {"issue_date": "9999-12-31", "due_date": None},
        {"due_date": "1066-10-14"},
        {"lines": [{**line, "quantity": "9" * 600_000, "unit_price": "9" * 600_000}]},
        {"lines": [line] * 501},
    ):
        for path in ("recheck", "decision"):
            body = {"action": "approve", "comment": "x", "invoice": {**good, **change}}
            response = harness.client.post(f"/api/documents/{document_id}/{path}", json=body)
            assert response.status_code in (413, 422), (path, list(change))
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "review"


def test_a_reviewer_can_approve_a_document_the_parser_refuses(
    harness: Harness, settings: Settings
) -> None:
    """Too many pages for the pipeline is not a reason to make an invoice unpayable:
    nothing is compared with the page, a check says so, and the reviewer answers for it."""
    data = invoice_data("bureauplus", line_count=330)
    document_id = harness.submit(data)
    detail = harness.client.get(f"/api/documents/{document_id}").json()
    assert (detail["status"], detail["reasons"]) == ("review", ["unreadable"])

    typed = perfect_reply(data)
    typed["issue_date"] = data.issue_date.isoformat()
    typed["due_date"] = data.due_date.isoformat() if data.due_date else None
    failing = harness.failing(document_id, typed)
    assert "document.unreadable" in failing
    response = harness.client.post(
        f"/api/documents/{document_id}/decision",
        json={
            "action": "approve",
            "invoice": typed,
            "comment": "entered from the paper copy",
            "acknowledged": failing,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert (settings.export_dir / f"document-{document_id:08d}.json").is_file()


def test_a_failed_document_can_be_read_again(harness: Harness) -> None:
    data = invoice_data("forez")
    harness.model.replies.update(
        {SMALL_MODEL: ModelError("unavailable"), LARGE_MODEL: ModelError("unavailable")}
    )
    document_id = harness.upload(data).json()["document"]["id"]
    harness.process()
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "failed"

    harness.model.replies[SMALL_MODEL] = perfect_reply(data)
    response = harness.client.post(f"/api/documents/{document_id}/reprocess")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    harness.process()
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "approved"
    assert harness.client.post(f"/api/documents/{document_id}/reprocess").status_code == 409


def test_reading_again_asked_twice_at_once_queues_one_job(harness: Harness) -> None:
    """A double click must not give a document two jobs: the second would undo the first."""
    data = invoice_data("forez")
    document_id = harness.misread(data)
    url = f"/api/documents/{document_id}/reprocess"
    first, second = together(lambda: harness.client.post(url), lambda: harness.client.post(url))
    assert sorted((first.status_code, second.status_code)) == [202, 409]
    with transaction(harness.context.sessions) as session:
        jobs = [job.status for job in session.scalars(select(Job).order_by(Job.id))]
    assert jobs == ["done", "queued"]

    harness.model.replies.update({SMALL_MODEL: perfect_reply(data)})
    harness.process()
    detail = harness.client.get(f"/api/documents/{document_id}").json()
    assert (detail["status"], detail["reasons"]) == ("approved", [])
    assert harness.count(Export) == 1


# ----------------------------------------------------------------- operations


def test_statistics_and_vendor_master(harness: Harness) -> None:
    harness.submit(invoice_data("forez"))
    harness.submit(invoice_data("fgs"))
    stats = harness.client.get("/api/stats").json()
    assert stats["by_status"]["approved"] == 1
    assert stats["by_status"]["review"] == 1
    assert stats["automation_rate"] == 0.5
    assert stats["jobs"]["done"] == 2
    assert stats["models"] == [SMALL_MODEL, LARGE_MODEL]

    vendors = harness.client.get("/api/vendors").json()
    assert len(vendors) == 24
    assert {"vendor_id", "name", "iban", "po_required"} <= set(vendors[0])


def test_probes(harness: Harness) -> None:
    assert harness.client.get("/healthz").json() == {"status": "ok"}
    ready = harness.client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["database"] is True


def test_readiness_fails_when_the_model_server_is_down(settings: Settings) -> None:
    settings.ollama_url = "http://127.0.0.1:9"  # nothing listens there
    with TestClient(create_app(settings, start_workers=False)) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["database"] is True
    assert set(body["models"].values()) == {False}


def test_metrics_report_outcomes_tiers_and_backlog(harness: Harness) -> None:
    before = harness.client.get("/metrics").text
    harness.submit(invoice_data("forez"))
    harness.misread(invoice_data("forez", seed=3, sequence=190))
    text = harness.client.get("/metrics").text

    def value(body: str, line: str) -> float:
        found = [row for row in body.splitlines() if row.startswith(line)]
        return float(found[0].rsplit(" ", 1)[1]) if found else 0.0

    approved = 'countersign_documents_total{mode="text",outcome="approved"}'
    assert value(text, approved) - value(before, approved) == 1
    review = 'countersign_documents_total{mode="text",outcome="review"}'
    assert value(text, review) - value(before, review) == 1
    failed = 'countersign_check_failures_total{family="arithmetic"}'
    assert value(text, failed) - value(before, failed) == 1
    assert 'countersign_jobs{status="done"} 2.0' in text
    assert 'countersign_documents{status="review"} 1.0' in text
    assert "countersign_model_seconds_bucket" in text


def test_the_application_starts_workers_that_read_what_is_uploaded(settings: Settings) -> None:
    """`serve` as it runs: the worker threads, not one a test drives by hand."""
    settings.workers = 2
    data = invoice_data("forez")
    model = ScriptedModel({SMALL_MODEL: perfect_reply(data)})
    with TestClient(create_app(settings, client=model, start_workers=True)) as client:
        names = [t.name for t in threading.enumerate() if t.name.startswith("worker-")]
        assert len(set(names)) == 2
        assert not {"worker-1", "worker-2"} & set(names)  # a name is unique across processes
        document_id = client.post(
            "/api/documents", files={"file": ("a.pdf", render_pdf(data), "application/pdf")}
        ).json()["document"]["id"]
        deadline = time.monotonic() + 30
        status = "queued"
        while status in ("queued", "processing") and time.monotonic() < deadline:
            time.sleep(0.05)
            status = client.get(f"/api/documents/{document_id}").json()["status"]
        assert status == "approved"
    assert not [t for t in threading.enumerate() if t.name.startswith("worker-")]


# -------------------------------------------------------------------- authentication


@pytest.fixture
def secured(settings: Settings) -> Iterator[Harness]:
    settings.api_keys = "ann:reviewer:key-reviewer, ops:operator:key-operator"
    model = ScriptedModel({})
    with TestClient(create_app(settings, client=model, start_workers=False)) as client:
        yield Harness(client, model)


def test_with_keys_configured_every_api_call_needs_one(secured: Harness) -> None:
    assert secured.client.get("/api/documents").status_code == 401
    assert secured.client.get("/api/stats", headers={"X-API-Key": "wrong"}).status_code == 401
    assert secured.upload(invoice_data("forez")).status_code == 401
    # Probes and the static console stay reachable: they carry no document data.
    assert secured.client.get("/healthz").status_code == 200
    assert secured.client.get("/").status_code == 200


def test_an_operator_can_submit_and_read_but_not_decide(secured: Harness) -> None:
    operator = {"X-API-Key": "key-operator"}
    reviewer = {"X-API-Key": "key-reviewer"}
    data = invoice_data("forez")
    wrong = perfect_reply(data)
    wrong["total_gross"] += 100
    secured.model.replies.update({SMALL_MODEL: wrong, LARGE_MODEL: wrong})
    uploaded = secured.upload(data, headers=operator)
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document"]["id"]
    secured.process()

    assert secured.client.get(f"/api/documents/{document_id}", headers=operator).status_code == 200
    decision = {"action": "reject", "comment": "no"}
    url = f"/api/documents/{document_id}/decision"
    assert secured.client.post(url, json=decision, headers=operator).status_code == 403
    assert (
        secured.client.post(f"/api/documents/{document_id}/reprocess", headers=operator).status_code
        == 403
    )
    accepted = secured.client.post(url, json=decision, headers=reviewer)
    assert accepted.status_code == 200
    detail = secured.client.get(f"/api/documents/{document_id}", headers=reviewer).json()
    assert detail["decided_by"] == "ann"
    assert detail["events"][0]["actor"] == "ops"


def test_a_request_is_refused_before_its_body_is_read(
    secured: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a key, and beyond the size limit: nobody makes the server spool a body."""
    parsed = []
    parse = MultiPartParser.parse

    async def counting(self: MultiPartParser) -> Any:
        parsed.append(True)
        return await parse(self)

    monkeypatch.setattr(MultiPartParser, "parse", counting)
    big = b"%PDF-" + bytes(secured.context.settings.max_upload_bytes + 128 * 1024)

    anonymous = secured.upload(big)
    assert (anonymous.status_code, parsed) == (401, [])
    oversized = secured.upload(big, headers={"X-API-Key": "key-operator"})
    assert (oversized.status_code, parsed) == (413, [])
    accepted = secured.upload(invoice_data("forez"), headers={"X-API-Key": "key-operator"})
    assert (accepted.status_code, parsed) == (201, [True])


def test_a_body_that_declares_no_size_is_cut_off_at_the_limit(harness: Harness) -> None:
    def endless() -> Iterator[bytes]:
        yield b'{"invoice": {"supplier_name": "'
        for _ in range(MAX_JSON_BYTES // 65536 + 2):
            yield b"x" * 65536
        yield b'"}}'

    response = harness.client.post(
        "/api/documents/1/recheck", content=endless(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_a_page_of_another_site_cannot_make_the_browser_change_anything(harness: Harness) -> None:
    """A form on another site, posted by the reviewer's browser, carries its Origin."""
    data = invoice_data("forez")
    foreign = {"Origin": "https://elsewhere.example"}
    assert harness.upload(data, headers=foreign).status_code == 403
    assert harness.client.get("/api/documents").json()["total"] == 0
    document_id = harness.misread(data)
    url = f"/api/documents/{document_id}/decision"
    assert harness.client.post(url, json={"action": "reject"}, headers=foreign).status_code == 403
    assert harness.client.get(f"/api/documents/{document_id}").json()["status"] == "review"

    own = {"Origin": "http://testserver"}
    assert harness.client.post(url, json={"action": "reject"}, headers=own).status_code == 200


def test_every_answer_forbids_framing_and_content_sniffing(harness: Harness) -> None:
    for path in ("/", "/app.js", "/healthz", "/api/stats", "/api/documents/9999", "/nothing"):
        headers = harness.client.get(path).headers
        assert headers["x-frame-options"] == "DENY", path
        assert headers["content-security-policy"] == "frame-ancestors 'none'", path
        assert headers["x-content-type-options"] == "nosniff", path


# ---------------------------------------------------------------------- review console


def test_the_console_is_served(harness: Harness) -> None:
    page = harness.client.get("/")
    assert page.status_code == 200
    assert "<title>Countersign</title>" in page.text
    assert harness.client.get("/app.js").status_code == 200
    assert harness.client.get("/app.css").status_code == 200


def test_the_console_never_writes_document_content_as_html() -> None:
    """Supplier names and line descriptions come from untrusted files."""
    script = (Path(WEB_DIR) / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in script, sink


def test_pages_are_served_as_images_rendered_on_the_server(harness: Harness) -> None:
    data = invoice_data("bureauplus", line_count=70)  # three pages
    uploaded = harness.upload(data).json()["document"]
    url = f"/api/documents/{uploaded['id']}"
    # The page count is the worker's to find; the pages can be asked for before that.
    assert harness.client.get(url).json()["page_count"] == 0
    for number in (1, 3):
        response = harness.client.get(f"{url}/pages/{number}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")
        assert "private" in response.headers["cache-control"]
    for number in (0, 4, 99):
        assert harness.client.get(f"{url}/pages/{number}").status_code == 404
    assert harness.client.get("/api/documents/9999/pages/1").status_code == 404

    harness.model.replies[SMALL_MODEL] = perfect_reply(data)
    harness.process()
    assert harness.client.get(url).json()["page_count"] == 3


def test_api_answers_are_not_stored_and_the_console_is_revalidated(harness: Harness) -> None:
    assert harness.client.get("/api/stats").headers["cache-control"] == "no-store"
    assert harness.client.get("/api/documents").headers["cache-control"] == "no-store"
    assert harness.client.get("/app.js").headers["cache-control"] == "no-cache"
    assert harness.client.get("/").headers["cache-control"] == "no-cache"


def console(scenario: str) -> dict[str, Any]:
    """Run the console's own script through a scenario, with network and timers scripted.

    `tests/console_harness.js` loads `web/app.js` unmodified against a small DOM stub.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = Path(__file__).with_name("console_harness.js")
    completed = subprocess.run(  # noqa: S603
        [node, str(harness), scenario], capture_output=True, text=True, timeout=60, check=False
    )
    assert completed.returncode == 0, completed.stderr
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def test_the_console_drops_an_answer_that_arrives_for_a_page_already_left() -> None:
    """The Overview answering late used to replace the document being corrected, and
    its timer, never cleared, did it again at every change of the statistics."""
    late = console("late_overview")
    assert late == {"view": "Document 7 invoice.pdf", "address": "#/documents/7", "timers": [10000]}
    orphan = console("orphan_timer")
    assert orphan["timers_on_the_document"] == [10000]
    assert orphan["view_after_the_statistics_changed"] == "Document 7 invoice.pdf"
    assert orphan["correction_still_on_screen"] is True


def test_the_console_shows_the_checks_of_what_the_form_holds() -> None:
    late = console("late_recheck")
    assert late["hint"].startswith("1 check still fails")
    assert late["decision"]["acknowledged"] == ["bank.on_file"]

    unseen = console("unseen_check")  # approving right after an edit: the recheck runs first
    assert unseen["decisions_sent"] == 0
    assert "checks changed" in unseen["toast"]
    assert unseen["hint"].startswith("1 check still fails")


def test_the_console_sends_one_request_for_two_clicks() -> None:
    assert console("double_click") == {"decisions_sent": 1, "reprocess_sent": 1}


def test_the_console_shows_a_date_as_the_day_it_is() -> None:
    """A date without a time, read as midnight UTC, is the day before in New York."""
    assert console("dates") == {
        "Europe/Paris": True,
        "America/New_York": True,
        "Pacific/Auckland": True,
    }


def test_the_console_asks_for_pages_one_by_one_when_their_number_is_unknown() -> None:
    assert console("unknown_page_count") == {"asked": [1, 2, 3], "shown": 2}

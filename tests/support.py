"""Helpers shared by the test suite: a scripted model, sample documents, master data."""

import json
import random
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from countersign.datagen import formats
from countersign.datagen.build import reference_data
from countersign.datagen.catalog import VENDORS_BY_KEY
from countersign.datagen.model import InvoiceData, make_invoice
from countersign.llm.client import ModelRequest, ModelResponse
from countersign.master import MasterData

TODAY = date(2026, 7, 1)
SMALL_MODEL = "small-model"
LARGE_MODEL = "large-model"

Reply = dict[str, Any] | str | Exception | Callable[[ModelRequest], Any]


class ScriptedModel:
    """A model client that answers what the test tells it to, and remembers the calls.

    `replies` maps a model name to a reply, or to a list of replies used in order. A
    reply is a dict (sent as JSON), a string (sent as is), an exception (raised), or a
    function of the request returning one of those.
    """

    def __init__(self, replies: dict[str, Reply | list[Reply]]) -> None:
        self.replies = replies
        self.calls: list[ModelRequest] = []

    def models_called(self) -> list[str]:
        return [call.model for call in self.calls]

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        reply = self.replies[request.model]
        if isinstance(reply, list):
            reply = reply.pop(0)
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return ModelResponse(
            content=content,
            model=request.model,
            prompt_tokens=1200,
            output_tokens=400,
            duration_s=2.5,
        )


def invoice_data(vendor_key: str = "breval", *, seed: int = 1, **options: Any) -> InvoiceData:
    """A consistent invoice of a catalogue supplier, the same for the same arguments."""
    options.setdefault("issue_date", date(2026, 3, 14))
    options.setdefault("sequence", 187)
    return make_invoice(random.Random(seed), VENDORS_BY_KEY[vendor_key], **options)


def master_data(purchase_orders: list[dict[str, str]] | None = None) -> MasterData:
    return MasterData.from_records(reference_data(purchase_orders or []))


def purchase_order(
    data: InvoiceData, number: str = "PO-2026-00412", **overrides: str
) -> dict[str, str]:
    """An open order that covers `data`, which is given its number."""
    data.po_number = number
    order = {
        "po_number": number,
        "vendor_id": data.vendor.vendor_id,
        "currency": data.vendor.spec.currency,
        "amount_net": f"{data.net}",
        "status": "open",
    }
    return {**order, **overrides}


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def perfect_reply(data: InvoiceData) -> dict[str, Any]:
    """What a model that reads the document perfectly answers, in the current prompt's shape."""
    spec = data.vendor.spec
    if not data.is_accounting_document:
        return {"document_type": "other", "lines": [], "vat_breakdown": []}
    return {
        "document_type": "credit_note" if data.kind == "credit_note" else "invoice",
        "invoice_number": data.number if data.print_number else None,
        "issue_date": formats.day(data.issue_date, spec) if data.print_issue_date else None,
        "due_date": formats.day(data.due_date, spec) if data.due_date else None,
        "currency": spec.currency,
        "supplier_name": data.vendor.name,
        "supplier_vat_id": data.vendor.vat_id,
        "supplier_siret": data.vendor.siret,
        "supplier_iban": data.printed_iban,
        "po_number": data.po_number,
        "referenced_invoice": data.original_invoice if data.kind == "credit_note" else None,
        "lines": [
            {
                "description": line.description,
                "quantity": _number(line.quantity),
                "unit_price": _number(line.unit_price),
                "amount": _number(line.amount),
                "vat_rate": _number(line.vat_rate),
            }
            for line in data.lines
        ],
        "allowance_total": _number(data.allowance or None),
        "charge_total": _number(data.charge or None),
        "total_net": _number(data.net),
        "vat_breakdown": [
            {"rate": _number(row.rate), "tax": _number(row.tax)} for row in data.vat_rows
        ],
        "total_tax": _number(data.tax),
        "total_gross": _number(data.gross),
    }


OTHER: dict[str, Any] = {"document_type": "other", "lines": [], "vat_breakdown": []}


# ------------------------------------------------------------ files written by hand


def text_pdf(pages: list[list[str]], size: float = 9) -> bytes:
    """A PDF with one page per list of lines, all in one fixed-width font."""
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    for lines in pages:
        canvas.setFont("Courier", size)
        for index, text in enumerate(lines):
            canvas.drawString(40, A4[1] - 50 - index * size * 1.35, text)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def raw_pdf(objects: list[bytes], trailer: bytes = b"") -> bytes:
    """A PDF written byte by byte: objects[i] is the body of object i + 1, object 1 the catalog."""
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        trailer,
        xref,
    )
    return bytes(out)


def stream(data: bytes, *, compress: bool = False) -> bytes:
    import zlib

    extra = b""
    if compress:
        data, extra = zlib.compress(data, 9), b" /Filter /FlateDecode"
    return b"<< /Length %d%s >>\nstream\n" % (len(data), extra) + data + b"\nendstream"


def one_page(
    content: bytes, *, mediabox: bytes = b"[0 0 595 842]", compress: bool = False
) -> bytes:
    """One page whose content stream is `content`; /F1 is Helvetica."""
    return raw_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox %s /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>" % mediabox,
            stream(content, compress=compress),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
    )


def merge(*pdfs: bytes) -> bytes:
    """The pages of several PDFs in one file."""
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf in pdfs:
        for page in PdfReader(BytesIO(pdf)).pages:
            writer.add_page(page)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def foreign_invoice(extra_lines: tuple[str, ...] = ()) -> tuple[bytes, dict[str, Any], MasterData]:
    """An invoice of a supplier on file, in a language no vocabulary of the checks covers.

    Dutch: the title "FACTUUR" and the labels of the totals mean nothing to the page
    evidence. Returns the file, a correct reading of it, and master data with its order.
    """
    from countersign.datagen.catalog import COMPANY
    from countersign.datagen.ids import spaced

    vendor = VENDORS_BY_KEY["vandijk"]
    order = {
        "po_number": "PO-2026-00412",
        "vendor_id": vendor.vendor_id,
        "currency": "EUR",
        "amount_net": "5000.00",
        "status": "open",
    }
    lines = [
        "Van Dijk Fasteners B.V. - Nijverheidsweg 21, 3534 AM Utrecht",
        f"BTW-nummer {vendor.vat_id}",
        "FACTUUR",
        "Factuurnummer: 202600187",
        "Factuurdatum: 14-03-2026",
        "Uw order: PO-2026-00412",
        f"Aan: {COMPANY.name}, 69007 Lyon",
        "Zeskantbout DIN 933 M10x40      10    24,50    245,00",
        "Totaal exclusief btw                        EUR 245,00",
        "Btw verlegd                                      0,00",
        "Totaal te betalen                           EUR 245,00",
        f"IBAN {spaced(vendor.iban or '')}",
        *extra_lines,
    ]
    reply = {
        "document_type": "invoice",
        "invoice_number": "202600187",
        "issue_date": "14-03-2026",
        "due_date": None,
        "currency": "EUR",
        "supplier_name": vendor.name,
        "supplier_vat_id": vendor.vat_id,
        "supplier_siret": None,
        "supplier_iban": vendor.iban,
        "po_number": "PO-2026-00412",
        "referenced_invoice": None,
        "lines": [
            {
                "description": "Zeskantbout",
                "quantity": 10,
                "unit_price": 24.5,
                "amount": 245.0,
                "vat_rate": 0,
            }
        ],
        "allowance_total": None,
        "charge_total": None,
        "total_net": 245.0,
        "vat_breakdown": [{"rate": 0, "tax": 0.0}],
        "total_tax": 0.0,
        "total_gross": 245.0,
    }
    return text_pdf([lines]), reply, master_data([order])

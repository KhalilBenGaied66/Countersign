"""Reading PDFs: text layer, scans, embedded e-invoices, and files that must be refused."""

import random
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from countersign.datagen.einvoice import attach, cii_xml
from countersign.datagen.model import as_credit_note
from countersign.datagen.render import render_pdf
from countersign.datagen.scan import scan
from countersign.parsing import einvoice
from countersign.parsing.pdf import (
    MAX_BYTES,
    MAX_PAGES,
    UnreadableDocument,
    parse_pdf,
    render_pages,
    sha256_of,
)
from countersign.pipeline.normalise import normalise
from tests.support import invoice_data


def test_text_layer_is_read_with_its_layout() -> None:
    data = invoice_data("breval")
    parsed = parse_pdf(render_pdf(data))
    assert parsed.has_text_layer
    assert parsed.page_count == 1
    assert data.number in parsed.text
    assert "Bréval Roulements SAS" in parsed.text
    # Columns stay on one line: a description and its amount are read together.
    first = data.lines[0]
    row = next(line for line in parsed.text.splitlines() if first.description in line)
    assert f"{first.amount:.2f}".replace(".", ",") in row
    assert parsed.sha256 == sha256_of(render_pdf(data))


def test_pages_are_separated_by_a_marker() -> None:
    parsed = parse_pdf(render_pdf(invoice_data("bureauplus", line_count=70)))
    assert parsed.page_count == 3
    assert "--- page 2 ---" in parsed.text
    assert "--- page 3 ---" in parsed.text


def test_a_scan_has_no_text_layer_and_renders_to_images() -> None:
    scanned = scan(render_pdf(invoice_data("forez")), random.Random(3))
    parsed = parse_pdf(scanned)
    assert not parsed.has_text_layer
    assert parsed.text.strip() == ""
    images = render_pages(scanned)
    assert len(images) == 1
    assert images[0].startswith(b"\x89PNG")


def test_scanning_is_reproducible() -> None:
    pdf = render_pdf(invoice_data("forez"))
    assert scan(pdf, random.Random(3)) == scan(pdf, random.Random(3))
    assert scan(pdf, random.Random(3)) != scan(pdf, random.Random(4))


def test_rendering_stops_at_the_page_limit() -> None:
    pdf = render_pdf(invoice_data("bureauplus", line_count=70))
    assert len(render_pages(pdf, max_pages=2)) == 2


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "not a PDF"),
        (b"hello, this is a text file", "not a PDF"),
        (b"%PDF-1.7\nthis is not really a pdf", "malformed"),
    ],
    ids=["empty", "text", "truncated"],
)
def test_files_that_are_not_usable_pdfs_are_refused(data: bytes, reason: str) -> None:
    with pytest.raises(UnreadableDocument, match=reason):
        parse_pdf(data)


def test_an_oversized_file_is_refused_before_it_is_parsed() -> None:
    with pytest.raises(UnreadableDocument, match="larger than"):
        parse_pdf(b"%PDF-" + bytes(MAX_BYTES))


def test_an_encrypted_pdf_is_refused() -> None:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(render_pdf(invoice_data()))))
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(UnreadableDocument, match="encrypted"):
        parse_pdf(buffer.getvalue())


def test_a_pdf_with_too_many_pages_is_refused() -> None:
    writer = PdfWriter()
    for _ in range(MAX_PAGES + 1):
        writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(UnreadableDocument, match="more than"):
        parse_pdf(buffer.getvalue())


def test_a_file_that_cannot_be_rendered_is_refused() -> None:
    with pytest.raises(UnreadableDocument):
        render_pages(b"%PDF-1.7\nbroken")


# ---------------------------------------------------------------------- e-invoices


def test_embedded_invoice_is_found_and_read_back() -> None:
    data = invoice_data("perrachon", line_count=4)  # several VAT rates
    pdf = attach(render_pdf(data), cii_xml(data))
    parsed = parse_pdf(pdf)
    xml = einvoice.find_embedded_invoice(parsed.attachments)
    assert xml is not None

    raw = einvoice.read_cii(xml)
    invoice = normalise(raw, decimal_separator=".").invoice
    assert invoice.document_type == "invoice"
    assert invoice.invoice_number == data.number
    assert invoice.issue_date == data.issue_date
    assert invoice.due_date == data.due_date
    assert invoice.currency == "EUR"
    assert invoice.supplier_vat_id == data.vendor.vat_id
    assert invoice.supplier_siret == data.vendor.siret
    assert invoice.supplier_iban == data.vendor.iban
    assert (invoice.total_net, invoice.total_tax, invoice.total_gross) == (
        data.net,
        data.tax,
        data.gross,
    )
    assert [line.amount for line in invoice.lines] == [line.amount for line in data.lines]
    assert [(row.rate, row.base, row.tax) for row in invoice.vat_breakdown] == [
        (row.rate, row.base, row.tax) for row in data.vat_rows
    ]


def test_embedded_credit_note_allowance_and_order_are_read() -> None:
    data = invoice_data("forez", allowance=True, charge=True)
    data.po_number = "PO-2026-00412"
    raw = einvoice.read_cii(cii_xml(data))
    invoice = normalise(raw, decimal_separator=".").invoice
    assert invoice.po_number == "PO-2026-00412"
    assert invoice.allowance_total == data.allowance
    assert invoice.charge_total == data.charge

    credit = invoice_data("forez")
    as_credit_note(credit, "2603-0100")
    assert einvoice.read_cii(cii_xml(credit)).document_type == "credit_note"


def test_no_allowance_is_read_as_absent_not_as_zero() -> None:
    raw = einvoice.read_cii(cii_xml(invoice_data("breval")))
    assert raw.allowance_total is None
    assert raw.charge_total is None


def test_attachment_names_are_matched_whatever_their_case() -> None:
    xml = cii_xml(invoice_data())
    assert einvoice.find_embedded_invoice({"Factur-X.XML": xml}) == xml
    assert einvoice.find_embedded_invoice({"zugferd-invoice.xml": xml}) == xml
    assert einvoice.find_embedded_invoice({"terms.pdf": b"..."}) is None


XXE = b"""<?xml version="1.0"?>
<!DOCTYPE invoice [<!ENTITY secret SYSTEM "file:///etc/passwd">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
  <note>&secret;</note>
</rsm:CrossIndustryInvoice>"""

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
  <note>&lol2;</note>
</rsm:CrossIndustryInvoice>"""


@pytest.mark.parametrize(
    "xml",
    [XXE, BILLION_LAUGHS, b"<not-closed", b"", b"<invoice><total>12</total></invoice>"],
    ids=["external-entity", "entity-expansion", "malformed", "empty", "not-cii"],
)
def test_hostile_or_foreign_xml_is_rejected(xml: bytes) -> None:
    with pytest.raises(einvoice.EInvoiceError):
        einvoice.read_cii(xml)


def test_a_document_type_code_this_reader_does_not_know_is_declined() -> None:
    xml = cii_xml(invoice_data()).replace(b">380<", b">325<")  # 325 is a pro forma invoice
    with pytest.raises(einvoice.EInvoiceError, match="unknown type"):
        einvoice.read_cii(xml)


def test_a_siren_is_not_reported_as_a_siret() -> None:
    data = invoice_data("breval")
    xml = cii_xml(data).replace(data.vendor.siret.encode(), data.vendor.siret[:9].encode())
    assert einvoice.read_cii(xml).supplier_siret is None


def test_amounts_keep_the_precision_of_the_xml() -> None:
    raw = einvoice.read_cii(cii_xml(invoice_data("breval")))
    assert raw.total_gross is not None
    assert Decimal(raw.total_gross).as_tuple().exponent == -2

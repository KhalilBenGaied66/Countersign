"""Write the embedded XML of a hybrid e-invoice, and attach it to a PDF.

The XML follows the structure of the UN/CEFACT Cross Industry Invoice used by Factur-X
and ZUGFeRD, limited to the elements `countersign.parsing.einvoice` reads. It has not
been validated against the official schemas and the PDF is not PDF/A-3: these files
exercise the reader, they are not conformant e-invoices.
"""

from io import BytesIO
from xml.etree.ElementTree import (
    Element,
    SubElement,
    register_namespace,
    tostring,
)

from pypdf import PdfReader, PdfWriter

from countersign.datagen.catalog import COMPANY
from countersign.datagen.model import InvoiceData

_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
EMBEDDED_NAME = "factur-x.xml"

for _prefix, _uri in (("rsm", _RSM), ("ram", _RAM), ("udt", _UDT)):
    register_namespace(_prefix, _uri)


def _ram(parent: Element, name: str, text: str | None = None, **attributes: str) -> Element:
    child = SubElement(parent, f"{{{_RAM}}}{name}", attributes)
    if text is not None:
        child.text = text
    return child


def _date(parent: Element, name: str, value: str) -> None:
    holder = _ram(parent, name)
    stamp = SubElement(holder, f"{{{_UDT}}}DateTimeString", {"format": "102"})
    stamp.text = value


def cii_xml(data: InvoiceData) -> bytes:
    vendor, spec = data.vendor, data.vendor.spec
    root = Element(f"{{{_RSM}}}CrossIndustryInvoice")
    context = SubElement(root, f"{{{_RSM}}}ExchangedDocumentContext")
    _ram(
        _ram(context, "GuidelineSpecifiedDocumentContextParameter"), "ID", "urn:cen.eu:en16931:2017"
    )

    document = SubElement(root, f"{{{_RSM}}}ExchangedDocument")
    _ram(document, "ID", data.number)
    _ram(document, "TypeCode", "381" if data.kind == "credit_note" else "380")
    _date(document, "IssueDateTime", data.issue_date.strftime("%Y%m%d"))

    transaction = SubElement(root, f"{{{_RSM}}}SupplyChainTradeTransaction")
    for position, line in enumerate(data.lines, start=1):
        item = _ram(transaction, "IncludedSupplyChainTradeLineItem")
        _ram(_ram(item, "AssociatedDocumentLineDocument"), "LineID", str(position))
        _ram(_ram(item, "SpecifiedTradeProduct"), "Name", line.description)
        price = _ram(_ram(item, "SpecifiedLineTradeAgreement"), "NetPriceProductTradePrice")
        _ram(price, "ChargeAmount", f"{line.unit_price}")
        delivery = _ram(item, "SpecifiedLineTradeDelivery")
        _ram(delivery, "BilledQuantity", f"{line.quantity}", unitCode="C62")
        settlement = _ram(item, "SpecifiedLineTradeSettlement")
        tax = _ram(settlement, "ApplicableTradeTax")
        _ram(tax, "TypeCode", "VAT")
        _ram(tax, "CategoryCode", "S" if line.vat_rate else "K")
        _ram(tax, "RateApplicablePercent", f"{line.vat_rate}")
        summation = _ram(settlement, "SpecifiedTradeSettlementLineMonetarySummation")
        _ram(summation, "LineTotalAmount", f"{line.amount}")

    agreement = _ram(transaction, "ApplicableHeaderTradeAgreement")
    seller = _ram(agreement, "SellerTradeParty")
    _ram(seller, "Name", vendor.name)
    if vendor.siret:
        _ram(_ram(seller, "SpecifiedLegalOrganization"), "ID", vendor.siret, schemeID="0002")
    _ram(_ram(seller, "PostalTradeAddress"), "CountryID", spec.country)
    if vendor.vat_id:
        _ram(_ram(seller, "SpecifiedTaxRegistration"), "ID", vendor.vat_id, schemeID="VA")
    buyer = _ram(agreement, "BuyerTradeParty")
    _ram(buyer, "Name", COMPANY.name)
    _ram(_ram(buyer, "SpecifiedTaxRegistration"), "ID", COMPANY.vat_id, schemeID="VA")
    if data.po_number:
        _ram(_ram(agreement, "BuyerOrderReferencedDocument"), "IssuerAssignedID", data.po_number)

    _ram(transaction, "ApplicableHeaderTradeDelivery")
    settlement = _ram(transaction, "ApplicableHeaderTradeSettlement")
    _ram(settlement, "InvoiceCurrencyCode", spec.currency)
    if data.printed_iban:
        means = _ram(settlement, "SpecifiedTradeSettlementPaymentMeans")
        _ram(means, "TypeCode", "30")
        _ram(_ram(means, "PayeePartyCreditorFinancialAccount"), "IBANID", data.printed_iban)
    for row in data.vat_rows:
        tax = _ram(settlement, "ApplicableTradeTax")
        _ram(tax, "CalculatedAmount", f"{row.tax}")
        _ram(tax, "TypeCode", "VAT")
        _ram(tax, "BasisAmount", f"{row.base}")
        _ram(tax, "CategoryCode", "S" if row.rate else "K")
        _ram(tax, "RateApplicablePercent", f"{row.rate}")
    if data.due_date:
        _date(
            _ram(settlement, "SpecifiedTradePaymentTerms"),
            "DueDateDateTime",
            f"{data.due_date:%Y%m%d}",
        )
    summation = _ram(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    if data.kind == "credit_note" and data.original_invoice:
        reference = _ram(settlement, "InvoiceReferencedDocument")
        _ram(reference, "IssuerAssignedID", data.original_invoice)
    _ram(summation, "LineTotalAmount", f"{data.lines_total}")
    _ram(summation, "ChargeTotalAmount", f"{data.charge:.2f}")
    _ram(summation, "AllowanceTotalAmount", f"{data.allowance:.2f}")
    _ram(summation, "TaxBasisTotalAmount", f"{data.net}")
    _ram(summation, "TaxTotalAmount", f"{data.tax}", currencyID=spec.currency)
    _ram(summation, "GrandTotalAmount", f"{data.gross}")
    _ram(summation, "DuePayableAmount", f"{data.gross}")
    body: bytes = tostring(root, encoding="utf-8")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + body


def attach(pdf: bytes, xml: bytes, name: str = EMBEDDED_NAME) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf)))
    writer.add_attachment(name, xml)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()

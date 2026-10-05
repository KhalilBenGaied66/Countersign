"""Read the structured invoice embedded in a hybrid PDF (Factur-X / ZUGFeRD).

A hybrid e-invoice is a PDF that carries its own data as an XML attachment in the
UN/CEFACT Cross Industry Invoice (CII) syntax. When that attachment exists there is
nothing to extract: it is read here, without any model, and then verified like every
other extraction. In particular its values must also be found in the visible page,
which is what catches a file whose XML and PDF disagree.

Only the elements this pipeline uses are read. The XML is parsed with defusedxml, with
DTDs refused: a document type declaration has no business in an invoice.
"""

from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from countersign.domain.schema import DocumentType, RawExtraction, RawLine, RawVatLine

EMBEDDED_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml")
TIER_NAME = "embedded-xml"

_NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
# UNTDID 1001 document type codes.
_INVOICE_CODES = {"380", "384", "389"}
_CREDIT_NOTE_CODES = {"381"}

_SETTLEMENT = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement"
_AGREEMENT = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
_SUMMATION = f"{_SETTLEMENT}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"


class EInvoiceError(Exception):
    """The attachment is not a readable CII invoice."""


def find_embedded_invoice(attachments: dict[str, bytes]) -> bytes | None:
    by_name = {name.lower(): content for name, content in attachments.items()}
    for name in EMBEDDED_NAMES:
        if name in by_name:
            return by_name[name]
    return None


def read_cii(xml: bytes) -> RawExtraction:
    """Read a CII invoice, or raise `EInvoiceError` when it is not one this reader handles.

    The caller then reads the page with a model instead. That is the case of a profile
    without line items (MINIMUM, BASIC WL) and of the document types this reader does
    not know: declining is safer than calling a prepayment invoice "not an invoice".
    """
    try:
        root = ElementTree.fromstring(xml, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException, ValueError, LookupError) as error:
        # LookupError: an encoding declaration naming a codec that does not exist.
        raise EInvoiceError(f"embedded XML rejected ({type(error).__name__})") from error
    if root.tag != f"{{{_NS['rsm']}}}CrossIndustryInvoice":
        raise EInvoiceError("embedded XML is not a Cross Industry Invoice")
    lines = [_line(item) for item in root.iterfind(_LINE, _NS)]
    if not lines:
        raise EInvoiceError("embedded invoice without line items")

    seller = f"{_AGREEMENT}/ram:SellerTradeParty"
    legal_id = _text(root, f"{seller}/ram:SpecifiedLegalOrganization/ram:ID")
    return RawExtraction(
        document_type=_document_type(_text(root, "rsm:ExchangedDocument/ram:TypeCode")),
        invoice_number=_text(root, "rsm:ExchangedDocument/ram:ID"),
        issue_date=_date(_text(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")),
        due_date=_date(
            _text(
                root,
                f"{_SETTLEMENT}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime"
                "/udt:DateTimeString",
            )
        ),
        currency=_text(root, f"{_SETTLEMENT}/ram:InvoiceCurrencyCode"),
        supplier_name=_text(root, f"{seller}/ram:Name"),
        supplier_vat_id=_text(
            root, f"{seller}/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']"
        ),
        # Scheme 0002 carries a SIREN (9 digits) or a SIRET (14): only the latter is one.
        supplier_siret=legal_id if legal_id and len(legal_id) == 14 else None,
        supplier_iban=_text(
            root,
            f"{_SETTLEMENT}/ram:SpecifiedTradeSettlementPaymentMeans"
            "/ram:PayeePartyCreditorFinancialAccount/ram:IBANID",
        ),
        po_number=_text(
            root, f"{_AGREEMENT}/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID"
        ),
        referenced_invoice=_text(
            root, f"{_SETTLEMENT}/ram:InvoiceReferencedDocument/ram:IssuerAssignedID"
        ),
        lines=lines,
        allowance_total=_nonzero(_text(root, f"{_SUMMATION}/ram:AllowanceTotalAmount")),
        charge_total=_nonzero(_text(root, f"{_SUMMATION}/ram:ChargeTotalAmount")),
        total_net=_text(root, f"{_SUMMATION}/ram:TaxBasisTotalAmount"),
        vat_breakdown=[
            RawVatLine(
                rate=_text(tax, "ram:RateApplicablePercent"),
                base=_text(tax, "ram:BasisAmount"),
                tax=_text(tax, "ram:CalculatedAmount"),
            )
            for tax in root.iterfind(f"{_SETTLEMENT}/ram:ApplicableTradeTax", _NS)
        ],
        total_tax=_text(root, f"{_SUMMATION}/ram:TaxTotalAmount"),
        total_gross=_text(root, f"{_SUMMATION}/ram:GrandTotalAmount"),
    )


_LINE = "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem"


def _line(item: Element) -> RawLine:
    settlement = "ram:SpecifiedLineTradeSettlement"
    return RawLine(
        description=_text(item, "ram:SpecifiedTradeProduct/ram:Name") or "",
        quantity=_text(item, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
        unit_price=_text(
            item, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"
        ),
        amount=_text(
            item,
            f"{settlement}/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
        ),
        vat_rate=_text(item, f"{settlement}/ram:ApplicableTradeTax/ram:RateApplicablePercent"),
    )


def _text(node: Element, path: str) -> str | None:
    found = node.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _nonzero(value: str | None) -> str | None:
    """An absent allowance is written 0.00 by many issuers: read it as absent."""
    return value if value and value.strip("0.") else None


def _date(value: str | None) -> str | None:
    """CII format 102 is YYYYMMDD; return it as an ISO date string."""
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _document_type(code: str | None) -> DocumentType:
    if code in _INVOICE_CODES:
        return "invoice"
    if code in _CREDIT_NOTE_CODES:
        return "credit_note"
    raise EInvoiceError(f"embedded invoice of an unknown type ({(code or 'none')[:8]})")

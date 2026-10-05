"""The checks an extraction must pass before it may be approved without a person.

None of them asks the model how confident it is. Each compares the extraction with
something the model does not control: arithmetic, a checksum, the text of the page, the
vendor master, the purchase order, the invoices already processed.

A failed check also says whether reading the document again could change the outcome
(`retriable`). A total that is not on the page is probably a misreading: a stronger
model should try. An IBAN that is printed on the page and differs from the one on file
is a fact about the document: no model will make it go away, and a person must look.
That distinction is what keeps escalation from being spent on documents it cannot fix.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

from countersign.domain.identifiers import iban_validity, siret_is_valid, vat_validity
from countersign.domain.normalize import normalize_reference
from countersign.domain.schema import Invoice, RawExtraction, VatLine
from countersign.master import MasterData, VendorRecord, reference_pattern
from countersign.verify.evidence import Evidence

CENT_TOLERANCE = Decimal("0.02")
# VAT is rounded per line by some suppliers and per rate by others.
VAT_TOLERANCE = Decimal("0.05")
PO_TOLERANCE = Decimal("1.02")
MONEY_DECIMALS = 2
MAX_AGE_DAYS = 400
MAX_TERM_DAYS = 200


class Check(BaseModel):
    id: str
    # Groups checks by what went wrong, for reporting and for the reviewer's screen.
    family: str
    passed: bool
    message: str
    blocking: bool = True
    retriable: bool = False
    fields: list[str] = []


@dataclass(frozen=True)
class Prior:
    """An earlier document that carries the same supplier and invoice number."""

    document_id: str
    document_type: str | None
    total_gross: Decimal | None
    issue_date: date | None = None
    # Who refused the earlier document, when a person did: sending an invoice again
    # must not undo that decision.
    rejected_by: str | None = None


class Ledger(Protocol):
    """Invoices already taken in, to detect one that is presented twice."""

    def find(self, vendor_id: str, invoice_number: str) -> Prior | None:
        """The earliest document with this supplier and invoice number, if any."""
        ...


@dataclass
class CheckContext:
    raw: RawExtraction
    invoice: Invoice
    unparsed: list[str]
    evidence: Evidence | None
    master: MasterData
    vendor: VendorRecord | None
    ledger: Ledger
    today: date
    # Date fields whose day and month could not be told apart (see `infer_day_first`).
    ambiguous: tuple[str, ...] = ()

    def on_page(self, name: str) -> bool | None:
        """Whether the value of a header field is printed on the page.

        None when the page cannot tell: there is no text layer, or, for a currency, the
        page names none.
        """
        if self.evidence is None:
            return None
        value = getattr(self.invoice, name)
        printed = getattr(self.raw, name, None)
        if value is None:
            return True
        if name in ("invoice_number", "po_number"):
            return self.evidence.has_reference(printed or value)
        if name in ("issue_date", "due_date"):
            return self.evidence.has_date(value)
        if name in ("supplier_vat_id", "supplier_siret", "supplier_iban"):
            return self.evidence.has_identifier(value)
        if name == "currency":
            return self.evidence.has_currency(value)
        if isinstance(value, Decimal):
            return self.evidence.has_number(value)
        return True

    def misread_possible(self, *fields: str) -> bool:
        """Whether a failure involving `fields` may come from the extraction itself.

        Without a text layer nothing proves a value was read correctly. With one, a
        value found on the page was at least copied from it.
        """
        return self.evidence is None or not all(self.on_page(name) for name in fields)


def _ok(check_id: str, family: str, message: str) -> Check:
    return Check(id=check_id, family=family, passed=True, message=message)


def _fail(
    check_id: str,
    family: str,
    message: str,
    *,
    retriable: bool,
    fields: tuple[str, ...] = (),
    blocking: bool = True,
) -> Check:
    return Check(
        id=check_id,
        family=family,
        passed=False,
        message=message,
        blocking=blocking,
        retriable=retriable,
        fields=list(fields),
    )


def run_checks(context: CheckContext) -> list[Check]:
    checks = _document_type(context)
    if context.invoice.document_type == "other":
        # Nothing else is expected of a document that is not an invoice.
        return checks
    for group in (
        _readable,
        _precision,
        _required,
        _addressee,
        _supplier,
        _bank,
        _invoice_number,
        _duplicate,
        _dates,
        _labelled_dates,
        _currency,
        _arithmetic,
        _labelled_totals,
        _purchase_order,
        _grounding,
    ):
        checks += group(context)
    return checks


def _document_type(context: CheckContext) -> list[Check]:
    checks = []
    reported = context.invoice.document_type
    heading = context.evidence.title_kind if context.evidence else None
    if heading and heading != reported:
        checks.append(
            _fail(
                "document.heading",
                "document_type",
                f"read as '{reported}' but the title of the page says '{heading}'",
                retriable=True,
                fields=("document_type",),
            )
        )
    elif heading:
        checks.append(_ok("document.heading", "document_type", f"the title says '{heading}'"))
    if reported == "other":
        checks.append(
            _fail(
                "document.accounting",
                "not_invoice",
                "not an invoice or a credit note",
                # Something else has to agree before a document is set aside: its own
                # title, or failing that a second reading.
                retriable=heading != "other",
                fields=("document_type",),
            )
        )
    return checks


def _readable(context: CheckContext) -> list[Check]:
    if not context.unparsed:
        return [_ok("values.readable", "extraction", "every printed value could be parsed")]
    return [
        _fail(
            "values.readable",
            "extraction",
            "values that could not be parsed: " + ", ".join(context.unparsed),
            retriable=True,
            fields=tuple(context.unparsed),
        )
    ]


def _precision(context: CheckContext) -> list[Check]:
    """Money has two decimals. A third one was computed by the reader, not printed."""
    invoice = context.invoice
    amounts: dict[str, Decimal | None] = {
        "total_net": invoice.total_net,
        "total_tax": invoice.total_tax,
        "total_gross": invoice.total_gross,
        "allowance_total": invoice.allowance_total,
        "charge_total": invoice.charge_total,
    }
    amounts.update(
        {f"lines[{index}].amount": line.amount for index, line in enumerate(invoice.lines)}
    )
    amounts.update(
        {f"vat_breakdown[{index}].tax": row.tax for index, row in enumerate(invoice.vat_breakdown)}
    )
    too_precise = [
        field
        for field, value in amounts.items()
        if value is not None and int(value.normalize().as_tuple().exponent) < -MONEY_DECIMALS
    ]
    if not too_precise:
        return []
    return [
        _fail(
            "values.precision",
            "extraction",
            f"amounts with more than {MONEY_DECIMALS} decimals: " + ", ".join(too_precise),
            retriable=True,
            fields=tuple(too_precise),
        )
    ]


def _required(context: CheckContext) -> list[Check]:
    invoice = context.invoice
    required = ["invoice_number", "issue_date", "currency", "total_net", "total_gross"]
    missing = [field for field in required if getattr(invoice, field) is None]
    if invoice.total_tax is None and invoice.total_net != invoice.total_gross:
        missing.append("total_tax")
    if not invoice.lines:
        missing.append("lines")
    if not missing:
        return [_ok("required.present", "missing_field", "all required fields are present")]
    return [
        _fail(
            "required.present",
            "missing_field",
            "missing: " + ", ".join(missing),
            retriable=True,
            fields=tuple(missing),
        )
    ]


def _addressee(context: CheckContext) -> list[Check]:
    """The page must name the buyer: an invoice meant for someone else is not ours to pay."""
    evidence, company = context.evidence, context.master.company
    if evidence is None:
        return []
    named = (
        evidence.has_identifier(company.vat_id)
        or bool(company.siret and evidence.has_identifier(company.siret))
        or evidence.names(company.name)
    )
    if named:
        return [_ok("buyer.addressed", "buyer", f"the page names {company.name}")]
    return [
        _fail(
            "buyer.addressed",
            "buyer",
            f"the page names neither {company.name} nor its identifiers",
            # A fact of the page, read without a model.
            retriable=False,
        )
    ]


def _supplier(context: CheckContext) -> list[Check]:
    invoice, vendor, company = context.invoice, context.vendor, context.master.company
    checks = []

    if invoice.supplier_vat_id and invoice.supplier_vat_id == company.vat_id:
        return [
            _fail(
                "supplier.not_buyer",
                "supplier",
                "the buyer's own VAT number was reported as the supplier's",
                retriable=True,
                fields=("supplier_vat_id",),
            )
        ]

    invalid = []
    if invoice.supplier_vat_id and vat_validity(invoice.supplier_vat_id) == "invalid":
        invalid.append("supplier_vat_id")
    if invoice.supplier_siret and not siret_is_valid(invoice.supplier_siret):
        invalid.append("supplier_siret")
    if invalid:
        checks.append(
            _fail(
                "supplier.identifiers",
                "supplier",
                "identifier with a wrong check digit or shape: " + ", ".join(invalid),
                retriable=context.misread_possible(*invalid),
                fields=tuple(invalid),
            )
        )

    if vendor is None:
        identifiers = [f for f in ("supplier_vat_id", "supplier_siret") if getattr(invoice, f)]
        checks.append(
            _fail(
                "supplier.known",
                "supplier",
                "the supplier is not in the vendor master",
                # A valid identifier that is on the page and unknown is a new supplier.
                retriable=not identifiers
                or bool(invalid)
                or context.misread_possible(*identifiers),
                fields=("supplier_vat_id", "supplier_siret", "supplier_name"),
            )
        )
        return checks

    checks.append(_ok("supplier.known", "supplier", f"matched {vendor.vendor_id} {vendor.name}"))
    differing = []
    if invoice.supplier_vat_id and vendor.vat_id and invoice.supplier_vat_id != vendor.vat_id:
        differing.append("supplier_vat_id")
    if invoice.supplier_siret and vendor.siret and invoice.supplier_siret != vendor.siret:
        differing.append("supplier_siret")
    if differing:
        checks.append(
            _fail(
                "supplier.consistent",
                "supplier",
                "differs from the vendor master: " + ", ".join(differing),
                retriable=context.misread_possible(*differing),
                fields=tuple(differing),
            )
        )
    return checks


def _bank(context: CheckContext) -> list[Check]:
    invoice, vendor, evidence = context.invoice, context.vendor, context.evidence
    checks = []
    iban = invoice.supplier_iban
    if iban and iban_validity(iban) != "valid":
        checks.append(
            _fail(
                "bank.checksum",
                "bank_details",
                "the IBAN does not pass its checksum",
                retriable=context.misread_possible("supplier_iban"),
                fields=("supplier_iban",),
            )
        )
    if vendor is None:
        return checks

    own = set(context.master.company.ibans)
    on_file = {vendor.iban} if vendor.iban else set()
    if iban and iban in own - on_file:
        checks.append(
            _fail(
                "bank.on_file",
                "bank_details",
                "the buyer's own account was reported as the supplier's",
                # The account a direct debit is taken from, read as the one to pay.
                retriable=True,
                fields=("supplier_iban",),
            )
        )
    elif iban and iban not in on_file:
        checks.append(
            _fail(
                "bank.on_file",
                "bank_details",
                "the IBAN is not the one on file for this supplier",
                retriable=context.misread_possible("supplier_iban"),
                fields=("supplier_iban",),
            )
        )
    elif iban:
        checks.append(_ok("bank.on_file", "bank_details", "the IBAN is the one on file"))

    if evidence is not None:
        # The buyer's own accounts may be printed: a direct debit names the one it uses.
        foreign = sorted(evidence.ibans - own - on_file)
        if foreign:
            checks.append(
                _fail(
                    "bank.sweep",
                    "bank_details",
                    "the page carries an account that is not on file: " + ", ".join(foreign),
                    retriable=False,
                    fields=("supplier_iban",),
                )
            )
        else:
            checks.append(_ok("bank.sweep", "bank_details", "no unknown account on the page"))
    return checks


def _invoice_number(context: CheckContext) -> list[Check]:
    invoice, vendor = context.invoice, context.vendor
    number = invoice.invoice_number
    if number is None:
        return []
    checks = []
    if context.master.po_regex.fullmatch(number) or number == invoice.po_number:
        checks.append(
            _fail(
                "number.not_order",
                "invoice_number",
                "the invoice number is a purchase order number",
                retriable=True,
                fields=("invoice_number",),
            )
        )
    if number == invoice.referenced_invoice:
        checks.append(
            _fail(
                "number.not_reference",
                "invoice_number",
                "the document is given the number of the invoice it refers to",
                retriable=True,
                fields=("invoice_number", "referenced_invoice"),
            )
        )
    example = vendor.invoice_number_example if vendor else None
    if vendor and invoice.document_type == "credit_note" and vendor.credit_note_number_example:
        example = vendor.credit_note_number_example
    if example:
        if reference_pattern(example).fullmatch(number):
            checks.append(
                _ok("number.shape", "invoice_number", "matches this supplier's numbering")
            )
        else:
            checks.append(
                _fail(
                    "number.shape",
                    "invoice_number",
                    f"'{number}' is not numbered like this supplier's documents ({example})",
                    # Several references are printed on an invoice: the wrong one may
                    # have been picked.
                    retriable=True,
                    fields=("invoice_number",),
                )
            )
    return checks


def _duplicate(context: CheckContext) -> list[Check]:
    invoice, vendor = context.invoice, context.vendor
    if vendor is None or invoice.invoice_number is None:
        return []
    prior = context.ledger.find(vendor.vendor_id, invoice.invoice_number)
    if prior is None:
        return [_ok("duplicate.unique", "duplicate", "first document with this number")]
    if prior.rejected_by:
        return [
            _fail(
                "duplicate.rejected",
                "duplicate",
                f"document {prior.document_id}, which carries this number, was rejected "
                f"by {prior.rejected_by}",
                # Sending a refused invoice again must not get it approved unseen.
                retriable=context.misread_possible("invoice_number"),
                fields=("invoice_number",),
            )
        ]
    same_document = (
        prior.document_type == invoice.document_type
        and prior.total_gross == invoice.total_gross
        and (
            prior.issue_date is None
            or invoice.issue_date is None
            or prior.issue_date == invoice.issue_date
        )
    )
    if same_document:
        return [
            _fail(
                "duplicate.unique",
                "duplicate",
                f"already received as document {prior.document_id}",
                retriable=context.misread_possible("invoice_number"),
                fields=("invoice_number",),
            )
        ]
    # Same number, another kind of document, another amount or another date: more likely
    # a number read from the wrong place (a credit note quotes the invoice it cancels, a
    # monthly invoice quotes last month's) than a copy. Setting it aside unseen would
    # lose a document, so it is read again, then shown.
    return [
        _fail(
            "duplicate.conflict",
            "duplicate",
            f"document {prior.document_id} has this number but is not the same document",
            retriable=True,
            fields=("invoice_number",),
        )
    ]


def _dates(context: CheckContext) -> list[Check]:
    invoice, today = context.invoice, context.today
    problems, fields = [], []
    if invoice.issue_date:
        if invoice.issue_date > today + timedelta(days=1):
            problems.append("issued in the future")
            fields.append("issue_date")
        elif invoice.issue_date < today - timedelta(days=MAX_AGE_DAYS):
            problems.append(f"issued more than {MAX_AGE_DAYS} days ago")
            fields.append("issue_date")
    if invoice.issue_date and invoice.due_date:
        term = (invoice.due_date - invoice.issue_date).days
        if term < 0:
            problems.append("due before it was issued")
            fields += ["issue_date", "due_date"]
        elif term > MAX_TERM_DAYS:
            problems.append(f"due more than {MAX_TERM_DAYS} days after issue")
            fields.append("due_date")
    checks = []
    if context.ambiguous:
        checks.append(
            _fail(
                "dates.order",
                "dates",
                "day and month cannot be told apart in "
                + ", ".join(context.ambiguous)
                + ": the dates printed on the page and the supplier's country disagree",
                # Another reading would copy the same date.
                retriable=False,
                fields=context.ambiguous,
            )
        )
    if not problems:
        return [*checks, _ok("dates.plausible", "dates", "dates are plausible")]
    unique = tuple(dict.fromkeys(fields))
    checks.append(
        _fail(
            "dates.plausible",
            "dates",
            "; ".join(problems),
            retriable=context.misread_possible(*unique),
            fields=unique,
        )
    )
    return checks


def _labelled_dates(context: CheckContext) -> list[Check]:
    """A date must be the one printed after its own label, when the label is known.

    Being on the page is not enough for a date: every invoice prints several. Without
    this, the issue date given as due date passes, on a page that says thirty days later.
    """
    evidence = context.evidence
    if evidence is None:
        return []
    elsewhere = []
    for name in ("issue_date", "due_date"):
        value = getattr(context.invoice, name)
        labelled = evidence.labelled_dates(name)
        if labelled and value not in labelled:
            printed = ", ".join(day.isoformat() for day in sorted(labelled))
            elsewhere.append(f"{name} read as {value} while its label carries {printed}")
    if not elsewhere:
        return []
    return [
        _fail(
            "dates.labelled",
            "dates",
            "; ".join(elsewhere),
            retriable=True,
            fields=tuple(part.split(" ", 1)[0] for part in elsewhere),
        )
    ]


def _currency(context: CheckContext) -> list[Check]:
    invoice, vendor = context.invoice, context.vendor
    if vendor is None or invoice.currency is None:
        return []
    if invoice.currency == vendor.currency:
        return [_ok("currency.expected", "currency", f"{vendor.currency}, as on file")]
    return [
        _fail(
            "currency.expected",
            "currency",
            f"{invoice.currency} instead of {vendor.currency}, the supplier's currency on file",
            # A currency the page really names is a fact of the document.
            retriable=context.misread_possible("currency"),
            fields=("currency",),
        )
    ]


def _arithmetic(context: CheckContext) -> list[Check]:
    invoice = context.invoice
    checks = []
    net, tax, gross = invoice.total_net, invoice.total_tax, invoice.total_gross

    if net is not None and invoice.lines:
        # A line without an amount counts for nothing: it must then be a free one, and
        # the others must add up without it.
        amounts = (line.amount for line in invoice.lines if line.amount is not None)
        lines_total = sum(amounts, Decimal(0))
        expected = lines_total - (invoice.allowance_total or 0) + (invoice.charge_total or 0)
        if abs(expected - net) <= CENT_TOLERANCE:
            checks.append(
                _ok("arithmetic.lines", "arithmetic", "the lines add up to the net total")
            )
        else:
            checks.append(
                _fail(
                    "arithmetic.lines",
                    "arithmetic",
                    f"lines, allowance and charge give {expected}, the net total is {net}",
                    # A skipped line and a wrong printed total look the same from here.
                    retriable=True,
                    fields=("lines", "total_net"),
                )
            )

    if invoice.document_type == "invoice" and gross is not None and gross < 0:
        checks.append(
            _fail(
                "arithmetic.sign",
                "arithmetic",
                f"an invoice with a negative total ({gross}): a credit note, or a sign misread",
                retriable=context.misread_possible("total_gross"),
                fields=("total_gross", "document_type"),
            )
        )

    if net is not None and gross is not None:
        if abs(net + (tax or 0) - gross) <= CENT_TOLERANCE:
            checks.append(_ok("arithmetic.totals", "arithmetic", "net plus tax equals gross"))
        else:
            checks.append(
                _fail(
                    "arithmetic.totals",
                    "arithmetic",
                    f"net {net} plus tax {tax or 0} is not the gross total {gross}",
                    retriable=True,
                    fields=("total_net", "total_tax", "total_gross"),
                )
            )

    vat_problem = _vat_problem(invoice)
    if vat_problem:
        checks.append(
            _fail(
                "arithmetic.vat",
                "arithmetic",
                vat_problem,
                retriable=True,
                fields=("vat_breakdown", "total_tax"),
            )
        )
    elif invoice.vat_breakdown:
        checks.append(_ok("arithmetic.vat", "arithmetic", "VAT matches its rates and bases"))

    off = [
        str(index + 1)
        for index, line in enumerate(invoice.lines)
        if line.quantity is not None
        and line.unit_price is not None
        and line.amount is not None
        and abs(line.quantity * line.unit_price - line.amount)
        > max(CENT_TOLERANCE, abs(line.amount) * Decimal("0.005"))
    ]
    if off:
        checks.append(
            _fail(
                "arithmetic.products",
                "arithmetic",
                "quantity times unit price is not the amount on line " + ", ".join(off),
                retriable=True,
                fields=("lines",),
            )
        )
    return checks


def _vat_problem(invoice: Invoice) -> str | None:
    """Describe the first inconsistency between VAT rows, rates and totals, if any.

    A VAT amount is tied to a rate and to a base: the base printed in the VAT table, the
    lines taxed at that rate, or the whole net total when there is a single rate. When
    the page gives none of these, each row still implies a base (its amount divided by
    its rate), and the bases implied must account for the net total. VAT that cannot be
    tied to anything is a problem in itself: this check does not pass for want of
    something to compare.
    """
    rows = invoice.vat_breakdown
    net, tax = invoice.total_net, invoice.total_tax
    if not rows:
        return _vat_without_rows(invoice)
    taxes = [row.tax for row in rows]
    if tax is not None and all(value is not None for value in taxes):
        total = sum((value for value in taxes if value is not None), Decimal(0))
        if abs(total - tax) > CENT_TOLERANCE:
            return f"VAT rows add up to {total}, the VAT total is {tax}"
    bases = [row.base for row in rows]
    if net is not None and all(value is not None for value in bases):
        total = sum((value for value in bases if value is not None), Decimal(0))
        if abs(total - net) > CENT_TOLERANCE:
            return f"taxable bases add up to {total}, the net total is {net}"

    derived = _bases_from_lines(invoice)
    untied = []
    for row in rows:
        if not row.tax:
            continue
        if not row.rate:
            return f"VAT of {row.tax} without a rate"
        base = row.base
        if base is None:
            # The lines know best: one of them may be outside VAT (a disbursement), and
            # then the only VAT row does not apply to the whole net total.
            base = derived.get(row.rate)
        if base is None and len(rows) == 1 and not derived:
            base = net
        if base is None:
            untied.append(row)
            continue
        expected = base * row.rate / 100
        if abs(expected - row.tax) > VAT_TOLERANCE:
            return f"{row.rate} % of {base} is {expected:.2f}, the document says {row.tax}"
    if untied and net is not None:
        return _implied_bases_problem(rows, net)
    return None


def _implied_bases_problem(rows: list[VatLine], net: Decimal) -> str | None:
    """Whether the bases the VAT rows imply account for the net total.

    178.76 of VAT at 20 % implies a base of 893.80. If the net total is 1 805.61 and no
    other row explains the difference, the amount is not 20 % of what it claims to tax.
    Only a row at 0 % may leave part of the net total unexplained.
    """
    taxed = [row for row in rows if row.rate and row.tax]
    implied = sum((row.tax * 100 / row.rate for row in taxed if row.tax and row.rate), Decimal(0))
    slack = sum((VAT_TOLERANCE * 100 / row.rate for row in taxed if row.rate), CENT_TOLERANCE)
    exempt = any(row.rate == 0 for row in rows)
    if implied - net > slack or (not exempt and net - implied > slack):
        return f"the VAT rows account for {implied:.2f} of a net total of {net}"
    return None


def _vat_without_rows(invoice: Invoice) -> str | None:
    net, tax = invoice.total_net, invoice.total_tax
    if not tax:
        return None
    derived = _bases_from_lines(invoice)
    if derived:
        expected = sum((base * rate / 100 for rate, base in derived.items()), Decimal(0))
        if abs(expected - tax) > VAT_TOLERANCE * len(derived):
            return f"the lines carry {expected:.2f} of VAT at their rates, the document says {tax}"
        return None
    rates = {line.vat_rate for line in invoice.lines if line.vat_rate is not None}
    if len(rates) == 1 and net is not None:
        rate = next(iter(rates))
        expected = net * rate / 100
        if abs(expected - tax) > VAT_TOLERANCE:
            return f"{rate} % of {net} is {expected:.2f}, the document says {tax}"
        return None
    return f"VAT of {tax} and no rate to check it against"


def _labelled_totals(context: CheckContext) -> list[Check]:
    """A total must be the amount printed next to its own label, when the label is known.

    Arithmetic alone cannot tell a correct reading from a tidy one: when a supplier
    misprints its net total, a reader that reports the taxable base from the VAT table
    instead hands over figures that add up perfectly.
    """
    evidence = context.evidence
    if evidence is None:
        return []
    elsewhere = []
    for field in ("total_net", "total_tax", "total_gross"):
        value = getattr(context.invoice, field)
        labelled = evidence.labelled_amounts(field)
        if value is not None and labelled and abs(value) not in labelled:
            printed = ", ".join(str(amount) for amount in sorted(labelled))
            elsewhere.append(f"{field} read as {value} while its label carries {printed}")
    if not elsewhere:
        return []
    return [
        _fail(
            "arithmetic.labelled",
            "arithmetic",
            "; ".join(elsewhere),
            retriable=True,
            fields=tuple(part.split(" ", 1)[0] for part in elsewhere),
        )
    ]


def _bases_from_lines(invoice: Invoice) -> dict[Decimal, Decimal]:
    """Taxable base of each rate, summed from the lines.

    Empty when the lines cannot tell: a line without a rate, or a document-level
    allowance or charge whose rate is not known.
    """
    if invoice.allowance_total or invoice.charge_total:
        return {}
    bases: dict[Decimal, Decimal] = {}
    for line in invoice.lines:
        if line.amount is None:
            continue
        if line.vat_rate is None:
            return {}
        bases[line.vat_rate] = bases.get(line.vat_rate, Decimal(0)) + line.amount
    return bases


def _purchase_order(context: CheckContext) -> list[Check]:
    invoice, vendor, evidence, master = (
        context.invoice,
        context.vendor,
        context.evidence,
        context.master,
    )
    if vendor is None:
        return []
    family = "purchase_order"
    reported = invoice.po_number
    # A credit note cancels an invoice: it may quote an order, it does not need one.
    credit_note = invoice.document_type == "credit_note"

    if reported is not None and not master.po_regex.fullmatch(reported):
        return [
            _fail(
                "po.shape",
                family,
                f"{reported} is not one of the buyer's order numbers",
                # A customer code or an earlier invoice number was taken for an order.
                retriable=True,
                fields=("po_number",),
            )
        ]

    if evidence is not None:
        printed = evidence.references(master.po_regex)
        if printed - ({reported} if reported else set()):
            return [
                _fail(
                    "po.sweep",
                    family,
                    "order numbers printed on the page and not reported: "
                    + ", ".join(sorted(printed - {reported})),
                    retriable=reported is None or reported not in printed,
                    fields=("po_number",),
                )
            ]

    if reported is None:
        if credit_note or not vendor.po_required:
            return []
        return [
            _fail(
                "po.required",
                family,
                "this supplier must quote a purchase order and none was found",
                retriable=evidence is None,
                fields=("po_number",),
            )
        ]

    misread = context.misread_possible("po_number")
    order = master.purchase_order(reported)
    if order is None:
        return [
            _fail(
                "po.exists",
                family,
                f"{reported} is not a known order",
                retriable=misread,
                fields=("po_number",),
            )
        ]
    problems = []
    if order.vendor_id != vendor.vendor_id:
        problems.append("the order was placed with another supplier")
    if not credit_note:
        if order.status != "open":
            problems.append("the order is closed")
        if invoice.currency and order.currency != invoice.currency:
            problems.append(f"the order is in {order.currency}")
        net = invoice.total_net
        if net is not None and abs(net) > order.amount_net * PO_TOLERANCE:
            problems.append(f"net total {net} exceeds the order ({order.amount_net})")
    if problems:
        return [
            _fail(
                "po.matches",
                family,
                "; ".join(problems),
                retriable=misread or context.misread_possible("total_net"),
                fields=("po_number", "total_net"),
            )
        ]
    return [_ok("po.matches", family, f"within order {normalize_reference(order.po_number)}")]


_GROUNDED_FIELDS = (
    "invoice_number",
    "issue_date",
    "due_date",
    "currency",
    "supplier_vat_id",
    "supplier_siret",
    "supplier_iban",
    "po_number",
    "total_net",
    "total_tax",
    "total_gross",
)


def _grounding(context: CheckContext) -> list[Check]:
    evidence = context.evidence
    if evidence is None:
        return []
    absent = [name for name in _GROUNDED_FIELDS if context.on_page(name) is False]
    absent_lines = [
        str(index + 1)
        for index, line in enumerate(context.invoice.lines)
        if line.amount is not None and not evidence.has_number(line.amount)
    ]
    # An amount printed elsewhere on the page is not the amount of this line: it has to
    # stand on the row of its unit price.
    displaced = [
        str(index + 1)
        for index, line in enumerate(context.invoice.lines)
        if line.amount is not None
        and line.unit_price is not None
        and str(index + 1) not in absent_lines
        and not evidence.has_row(line.unit_price, line.amount)
    ]
    checks = []
    if absent:
        checks.append(
            _fail(
                "grounding.header",
                "grounding",
                "not found on the page: " + ", ".join(absent),
                retriable=True,
                fields=tuple(absent),
            )
        )
    else:
        checks.append(_ok("grounding.header", "grounding", "every header value is on the page"))
    if absent_lines or displaced:
        problems = []
        if absent_lines:
            problems.append("line amounts not found on the page: line " + ", ".join(absent_lines))
        if displaced:
            problems.append(
                "unit price and amount not printed on one row: line " + ", ".join(displaced)
            )
        checks.append(
            _fail(
                "grounding.lines",
                "grounding",
                "; ".join(problems),
                retriable=True,
                fields=("lines",),
            )
        )
    return checks


def blocking_failures(checks: list[Check]) -> list[Check]:
    return [check for check in checks if not check.passed and check.blocking]

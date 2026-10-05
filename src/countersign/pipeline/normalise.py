"""From strings as printed to numbers and dates.

Two conventions are a property of the whole document and are inferred here before any
value is parsed: the decimal separator and whether dates are written day first. Both
are inferred from unambiguous values, never asked of the model.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from countersign.domain.identifiers import compact, digits_only
from countersign.domain.normalize import (
    DecimalSeparator,
    date_candidates,
    day_first_vote,
    day_first_votes_in,
    decimal_separator_vote,
    normalize_currency,
    normalize_reference,
    parse_amount,
)
from countersign.domain.schema import Invoice, Line, RawExtraction, VatLine
from countersign.master import normalize_vat_id

# The longest reference kept. Nothing an invoice prints is longer, and the column that
# holds an invoice number is this wide.
MAX_REFERENCE_CHARACTERS = 64

# Longest gap between issue and due date still read as a payment term.
_MAX_TERM_DAYS = 120
# Countries where a numeric date is written month first.
_MONTH_FIRST_COUNTRIES = frozenset({"US"})


@dataclass(frozen=True)
class Normalised:
    invoice: Invoice
    # Fields that hold a printed value the parsers could not read.
    unparsed: list[str]
    decimal_separator: DecimalSeparator | None
    day_first: bool
    # Date fields that can be read two ways while the page and the supplier's country
    # disagree on which.
    ambiguous: tuple[str, ...] = ()


def _printed_numbers(raw: RawExtraction) -> Iterable[str]:
    fields = (raw.total_net, raw.total_tax, raw.total_gross, raw.allowance_total, raw.charge_total)
    yield from (value for value in fields if value)
    for line in raw.lines:
        yield from (value for value in (line.quantity, line.unit_price, line.amount) if value)
    for row in raw.vat_breakdown:
        yield from (value for value in (row.base, row.tax) if value)


def infer_decimal_separator(raw: RawExtraction) -> DecimalSeparator | None:
    votes = Counter(
        vote for printed in _printed_numbers(raw) if (vote := decimal_separator_vote(printed))
    )
    if not votes or votes[","] == votes["."]:
        return None
    return "," if votes[","] > votes["."] else "."


def _majority(votes: list[bool]) -> bool:
    return sum(votes) * 2 >= len(votes)


def infer_day_first(
    raw: RawExtraction, text: str | None, vendor_country: str | None
) -> tuple[bool, bool]:
    """Decide how to read an ambiguous numeric date such as 03/04/2026.

    Returns the answer, and whether it is disputed. In order: a date of the extraction
    that can only be read one way; the reading under which the due date follows the
    issue date by a plausible payment term; then the convention of the supplier's
    country and the other dates of the page. Those two must agree. A page also carries
    text nobody sees, and three dates written there must not be able to move a due date
    by six months: when they contradict the country on file, the answer is disputed and
    a person reads the date. Day first, the convention outside the US, when nothing tells.
    """
    printed = [value for value in (raw.issue_date, raw.due_date) if value]
    votes = [vote for value in printed if (vote := day_first_vote(value)) is not None]
    if votes:
        return _majority(votes), False

    if raw.issue_date and raw.due_date:
        issue, due = date_candidates(raw.issue_date), date_candidates(raw.due_date)
        if len(issue) == 2 and len(due) == 2:
            plausible = [
                0 <= (due[reading] - issue[reading]).days <= _MAX_TERM_DAYS for reading in (0, 1)
            ]
            if plausible[0] != plausible[1]:
                return plausible[0], False

    on_page = day_first_votes_in(text) if text else []
    if vendor_country is None:
        return (_majority(on_page) if on_page else True), False
    convention = vendor_country not in _MONTH_FIRST_COUNTRIES
    return convention, bool(on_page) and _majority(on_page) != convention


def _order_number(printed: str, pattern: re.Pattern[str] | None) -> str:
    """The buyer's order number inside what was copied, when letters are glued to it.

    Text extraction runs two columns together when they touch: "PO-2026-20260France".
    The buyer issues its order numbers and knows their shape, so the number can be told
    from the word. Digits next to it are another matter: a longer number is not this one.
    """
    value = normalize_reference(printed)
    if pattern is None or pattern.fullmatch(value):
        return value
    found = pattern.findall(value)
    if len(found) == 1 and isinstance(found[0], str):
        rest = value.replace(found[0], "", 1)
        if rest.isalpha():
            return found[0]
    return value


def normalise(
    raw: RawExtraction,
    *,
    text: str | None = None,
    vendor_country: str | None = None,
    decimal_separator: DecimalSeparator | None = None,
    order_pattern: re.Pattern[str] | None = None,
) -> Normalised:
    separator = decimal_separator or infer_decimal_separator(raw)
    day_first, disputed = infer_day_first(raw, text, vendor_country)
    unparsed: list[str] = []
    ambiguous: list[str] = []

    def amount(field: str, printed: str | None) -> Decimal | None:
        if printed is None:
            return None
        value = parse_amount(printed, separator)
        if value is None:
            unparsed.append(field)
        return value

    def magnitude(field: str, printed: str | None) -> Decimal | None:
        value = amount(field, printed)
        return abs(value) if value is not None else None

    def day(field: str, printed: str | None) -> date | None:
        if printed is None:
            return None
        candidates = date_candidates(printed)
        if not candidates:
            unparsed.append(field)
            return None
        if len(candidates) == 1:
            return candidates[0]
        if disputed:
            ambiguous.append(field)
        return candidates[0] if day_first else candidates[1]

    def reference(field: str, printed: str | None) -> str | None:
        if printed is None:
            return None
        value = normalize_reference(printed)
        if len(value) > MAX_REFERENCE_CHARACTERS:
            unparsed.append(field)
            return None
        return value

    currency = normalize_currency(raw.currency) if raw.currency else None
    if raw.currency and currency is None:
        unparsed.append("currency")

    invoice = Invoice(
        document_type=raw.document_type,
        invoice_number=reference("invoice_number", raw.invoice_number),
        issue_date=day("issue_date", raw.issue_date),
        due_date=day("due_date", raw.due_date),
        currency=currency,
        supplier_name=raw.supplier_name,
        supplier_vat_id=normalize_vat_id(raw.supplier_vat_id) if raw.supplier_vat_id else None,
        supplier_siret=digits_only(raw.supplier_siret) if raw.supplier_siret else None,
        supplier_iban=compact(raw.supplier_iban) if raw.supplier_iban else None,
        po_number=reference(
            "po_number", _order_number(raw.po_number, order_pattern) if raw.po_number else None
        ),
        referenced_invoice=reference("referenced_invoice", raw.referenced_invoice),
        lines=[
            Line(
                description=line.description or "",
                quantity=amount(f"lines[{index}].quantity", line.quantity),
                unit_price=amount(f"lines[{index}].unit_price", line.unit_price),
                amount=amount(f"lines[{index}].amount", line.amount),
                vat_rate=amount(f"lines[{index}].vat_rate", line.vat_rate),
            )
            for index, line in enumerate(raw.lines)
            # A row without any figure is a comment or a sub-heading, not a line.
            if line.quantity or line.unit_price or line.amount
        ],
        allowance_total=magnitude("allowance_total", raw.allowance_total),
        charge_total=magnitude("charge_total", raw.charge_total),
        total_net=amount("total_net", raw.total_net),
        vat_breakdown=[
            VatLine(
                rate=amount(f"vat_breakdown[{index}].rate", row.rate),
                base=amount(f"vat_breakdown[{index}].base", row.base),
                tax=amount(f"vat_breakdown[{index}].tax", row.tax),
            )
            for index, row in enumerate(raw.vat_breakdown)
        ],
        total_tax=amount("total_tax", raw.total_tax),
        total_gross=amount("total_gross", raw.total_gross),
    )
    return Normalised(invoice, unparsed, separator, day_first, tuple(ambiguous))

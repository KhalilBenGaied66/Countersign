"""The content of a synthetic document, and its ground truth.

`InvoiceData` holds what is *printed*: scenarios may alter it (a wrong total, another
IBAN) and the ground truth follows, because the task is to read the document as it is.
Whether the document should then be approved is a separate label, set by the scenario.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from countersign.datagen.catalog import Item, Vendor
from countersign.datagen.formats import quantize
from countersign.domain.normalize import normalize_reference
from countersign.domain.schema import Invoice, Line, VatLine

Kind = Literal[
    "invoice",
    "credit_note",
    "quote",
    "delivery_note",
    "reminder",
    "proforma",
    "order_confirmation",
]


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal
    vat_rate: Decimal
    quantity_places: int = 0
    price_places: int = 2
    reference: str = ""


@dataclass
class VatRow:
    rate: Decimal
    base: Decimal
    tax: Decimal


@dataclass
class InvoiceData:
    vendor: Vendor
    number: str
    issue_date: date
    lines: list[LineItem]
    net: Decimal
    vat_rows: list[VatRow]
    tax: Decimal
    gross: Decimal
    kind: Kind = "invoice"
    due_date: date | None = None
    po_number: str | None = None
    allowance: Decimal = Decimal(0)
    allowance_label: str = ""
    charge: Decimal = Decimal(0)
    printed_iban: str | None = None
    printed_bic: str | None = None
    customer_no: str = ""
    original_invoice: str | None = None
    notes: list[str] = field(default_factory=list)
    hidden_text: list[str] = field(default_factory=list)
    stamp: str | None = None
    show_buyer_vat: bool = True
    print_number: bool = True
    print_issue_date: bool = True

    @property
    def lines_total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal(0))

    @property
    def is_accounting_document(self) -> bool:
        return self.kind in ("invoice", "credit_note")


def _pick_quantity(rng: random.Random, item: Item) -> Decimal:
    low, high = item.quantity
    if item.quantity_decimals == 0:
        return Decimal(rng.randint(int(low), int(high)))
    return quantize(Decimal(str(rng.uniform(low, high))), item.quantity_decimals)


def _pick_lines(rng: random.Random, vendor: Vendor, count: int) -> list[LineItem]:
    items = list(vendor.spec.items)
    chosen = rng.sample(items, count) if count <= len(items) else rng.choices(items, k=count)
    zero_rated = vendor.spec.vat_mode != "domestic"
    lines = []
    for position, item in enumerate(chosen, start=1):
        quantity = _pick_quantity(rng, item)
        price = quantize(Decimal(str(rng.uniform(*item.price))), item.price_decimals)
        lines.append(
            LineItem(
                description=item.description,
                quantity=quantity,
                unit=item.unit,
                unit_price=price,
                amount=quantize(quantity * price),
                vat_rate=Decimal(0) if zero_rated else Decimal(item.vat_rate),
                quantity_places=item.quantity_decimals,
                price_places=item.price_decimals,
                reference=(
                    f"{vendor.spec.key[:2].upper()}{rng.randint(10000, 99999)}-{position:02d}"
                ),
            )
        )
    return lines


def compute_totals(data: InvoiceData) -> None:
    """Recompute net, VAT rows, tax and gross from the lines, allowance and charge."""
    bases: dict[Decimal, Decimal] = {}
    for line in data.lines:
        bases[line.vat_rate] = bases.get(line.vat_rate, Decimal(0)) + line.amount
    # The allowance and the charge follow the rate that carries most of the invoice.
    main_rate = max(bases, key=lambda rate: abs(bases[rate]))
    bases[main_rate] += data.charge - data.allowance
    data.vat_rows = [
        VatRow(rate=rate, base=base, tax=quantize(base * rate / 100))
        for rate, base in sorted(bases.items())
    ]
    data.net = sum((row.base for row in data.vat_rows), Decimal(0))
    data.tax = sum((row.tax for row in data.vat_rows), Decimal(0))
    data.gross = data.net + data.tax


def make_invoice(
    rng: random.Random,
    vendor: Vendor,
    *,
    issue_date: date,
    sequence: int,
    line_count: int | None = None,
    allowance: bool = False,
    charge: bool = False,
) -> InvoiceData:
    """Draw a consistent invoice from the supplier's catalogue."""
    spec = vendor.spec
    count = line_count or rng.randint(1, min(6, len(spec.items)))
    data = InvoiceData(
        vendor=vendor,
        number=spec.number_pattern.format(
            year=issue_date.year,
            yy=issue_date.year % 100,
            mm=f"{issue_date.month:02d}",
            seq=sequence,
        ),
        issue_date=issue_date,
        due_date=issue_date + timedelta(days=spec.terms_days) if spec.prints_due_date else None,
        lines=_pick_lines(rng, vendor, count),
        net=Decimal(0),
        vat_rows=[],
        tax=Decimal(0),
        gross=Decimal(0),
        printed_iban=vendor.iban if spec.prints_iban else None,
        printed_bic=vendor.bic if spec.prints_iban else None,
        customer_no=f"{rng.randint(1000, 99999):06d}",
    )
    single_rate = len({line.vat_rate for line in data.lines}) == 1
    if allowance and single_rate:
        percent = rng.choice((2, 3, 5, 10))
        data.allowance = quantize(data.lines_total * percent / 100)
        data.allowance_label = f"{percent} %"
    if charge:
        data.charge = quantize(Decimal(str(rng.uniform(12, 85))))
    compute_totals(data)
    return data


def as_credit_note(data: InvoiceData, original_number: str) -> None:
    """Turn an invoice into the credit note that cancels part of it."""
    data.kind = "credit_note"
    data.original_invoice = original_number
    data.po_number = None
    data.due_date = None
    data.allowance, data.allowance_label, data.charge = Decimal(0), "", Decimal(0)
    if data.vendor.spec.credit_sign == "negative":
        for line in data.lines:
            line.quantity = -line.quantity
            line.amount = -line.amount
    compute_totals(data)


def truth_of(data: InvoiceData) -> Invoice:
    """What a perfect reader would extract from the printed document."""
    if not data.is_accounting_document:
        return Invoice(document_type="other")
    vendor = data.vendor
    return Invoice(
        document_type="credit_note" if data.kind == "credit_note" else "invoice",
        invoice_number=normalize_reference(data.number) if data.print_number else None,
        issue_date=data.issue_date if data.print_issue_date else None,
        due_date=data.due_date,
        currency=vendor.spec.currency,
        supplier_name=vendor.name,
        supplier_vat_id=vendor.vat_id,
        supplier_siret=vendor.siret,
        supplier_iban=data.printed_iban,
        po_number=data.po_number,
        referenced_invoice=(
            normalize_reference(data.original_invoice) if data.original_invoice else None
        ),
        lines=[
            Line(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
                vat_rate=line.vat_rate,
            )
            for line in data.lines
        ],
        allowance_total=data.allowance or None,
        charge_total=data.charge or None,
        total_net=data.net,
        vat_breakdown=[VatLine(rate=row.rate, base=row.base, tax=row.tax) for row in data.vat_rows],
        total_tax=data.tax,
        total_gross=data.gross,
    )

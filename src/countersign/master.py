"""Reference data the buyer already holds: itself, its suppliers, its purchase orders.

This is the independent source every extraction is checked against. A model can
misread a page, and a page can lie; neither can change what the vendor master says
the supplier's bank account is.

The prototype loads three JSON files. In production these records come from the ERP,
and the loader below is the seam to replace.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from countersign.domain.identifiers import compact, digits_only
from countersign.domain.normalize import normalize_name, normalize_reference
from countersign.domain.schema import RawExtraction


class _Record(BaseModel):
    """Identifiers are held compact, however the system of record writes them.

    A SIRET kept as "960 370 096 00062" or an IBAN kept in groups of four would otherwise
    differ from the same number read from a page, and stop every invoice of the supplier.
    """

    @field_validator("vat_id", check_fields=False)
    @classmethod
    def _compact_vat_id(cls, value: str | None) -> str | None:
        return normalize_vat_id(value) if value else value

    @field_validator("siret", check_fields=False)
    @classmethod
    def _compact_siret(cls, value: str | None) -> str | None:
        return digits_only(value) if value else value

    @field_validator("iban", check_fields=False)
    @classmethod
    def _compact_iban(cls, value: str | None) -> str | None:
        return compact(value) if value else value


class VendorRecord(_Record):
    vendor_id: str
    name: str
    country: str
    currency: str
    vat_id: str | None = None
    siret: str | None = None
    iban: str | None = None
    payment_terms_days: int = 30
    po_required: bool = False
    invoice_number_example: str | None = None
    # For a supplier that numbers its credit notes in a series of their own.
    credit_note_number_example: str | None = None


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_id: str
    currency: str
    amount_net: Decimal
    status: Literal["open", "closed"] = "open"


class CompanyRecord(_Record):
    name: str
    vat_id: str
    siret: str | None = None
    ibans: list[str] = []
    # Purchase order numbers are issued by the buyer, so their shape is known.
    po_pattern: str = r"PO-\d{4}-\d{5}"
    # Shown to the model, which is otherwise tempted by any reference on the page.
    po_example: str = "PO-2026-00123"

    @field_validator("ibans")
    @classmethod
    def _compact_ibans(cls, value: list[str]) -> list[str]:
        return [compact(iban) for iban in value]


@dataclass(frozen=True)
class VendorMatch:
    vendor: VendorRecord | None
    # Which printed identifier led to the record: "vat_id", "siret" or "name".
    matched_on: str | None = None


def reference_pattern(example: str) -> re.Pattern[str]:
    """What a supplier's numbers look like, told from one of them.

    Letters and symbols are kept as they are. Digits written with leading zeros are a
    counter padded to that width: after "00187" come "00188" and, one day, "100000",
    never "0018" or "187". Other digits may be of any length: "2026" will be "2027".
    A purchase order number or a customer account from the same page does not fit.
    """
    parts = []
    for run in re.findall(r"\d+|\D+", normalize_reference(example)):
        if not run.isdigit():
            parts.append(re.escape(run))
        elif run.startswith("0"):
            width = len(run)
            parts.append(rf"(?:\d{{{width}}}|[1-9]\d{{{width},}})")
        else:
            parts.append(r"\d+")
    return re.compile("".join(parts))


class MasterData:
    def __init__(
        self,
        company: CompanyRecord,
        vendors: list[VendorRecord],
        purchase_orders: list[PurchaseOrder],
    ) -> None:
        self.company = company
        self.vendors = vendors
        self._by_vat = {v.vat_id: v for v in vendors if v.vat_id}
        self._by_siret = {v.siret: v for v in vendors if v.siret}
        self._by_name = {normalize_name(v.name): v for v in vendors}
        self._orders = {normalize_reference(po.po_number): po for po in purchase_orders}
        self.po_regex = re.compile(company.po_pattern)

    @classmethod
    def from_records(cls, records: Mapping[str, Any]) -> "MasterData":
        """Build from plain data: a company, a list of vendors, a list of purchase orders."""
        return cls(
            company=CompanyRecord.model_validate(records["company"]),
            vendors=[VendorRecord.model_validate(item) for item in records["vendors"]],
            purchase_orders=[
                PurchaseOrder.model_validate(item) for item in records["purchase_orders"]
            ],
        )

    @classmethod
    def load(cls, directory: Path) -> "MasterData":
        """Read `company.json`, `vendors.json` and `purchase_orders.json` from a directory."""
        names = ("company", "vendors", "purchase_orders")
        return cls.from_records(
            {
                name: json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
                for name in names
            }
        )

    def vendor(self, vendor_id: str) -> VendorRecord | None:
        return next((v for v in self.vendors if v.vendor_id == vendor_id), None)

    def purchase_order(self, number: str) -> PurchaseOrder | None:
        return self._orders.get(normalize_reference(number))

    def match_vendor(self, raw: RawExtraction) -> VendorMatch:
        """Find the supplier of an extraction in the vendor master.

        A registered identifier wins. The name alone identifies a supplier only when
        neither the master nor the document holds an identifier (a US supplier has no
        VAT number): a known name under an unknown VAT number is a different company
        until a person says otherwise.
        """
        if raw.supplier_vat_id and (
            vendor := self._by_vat.get(normalize_vat_id(raw.supplier_vat_id))
        ):
            return VendorMatch(vendor, "vat_id")
        if raw.supplier_siret and (vendor := self._by_siret.get(digits_only(raw.supplier_siret))):
            return VendorMatch(vendor, "siret")
        if raw.supplier_name and not raw.supplier_vat_id and not raw.supplier_siret:
            vendor = self._by_name.get(normalize_name(raw.supplier_name))
            if vendor and not vendor.vat_id and not vendor.siret:
                return VendorMatch(vendor, "name")
        return VendorMatch(None)


def normalize_vat_id(printed: str) -> str:
    """Compact a printed VAT number; a Swiss UID drops its "MWST"/"TVA"/"IVA" suffix."""
    value = compact(printed)
    if value.startswith("CHE"):
        return value[:12]
    return value

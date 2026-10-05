"""Render an `InvoiceData` as a PDF, in the layout of its supplier.

Seven layouts cover what makes real invoices hard to read: supplier and buyer blocks
side by side, identifiers buried in a small-print footer, fixed-width ERP printouts,
quantity-first tables, a due date that only appears in a sentence, multi-page tables
with carried-forward subtotals. Output is byte-stable for a given input (`invariant`).
"""

import html
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from countersign.datagen import formats, ids
from countersign.datagen.catalog import COMPANY
from countersign.datagen.model import InvoiceData, LineItem

_BOLD = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}
_MARGIN = 18 * mm
_GREY = colors.HexColor("#6b7280")
_LIGHT = colors.HexColor("#f3f4f6")
_LEDGER_WIDTH = 96
_PRICE_COLUMNS = ("unit_price", "vat", "amount")

Story = list[Flowable]
PageHook = Callable[[Canvas, Any], None]


def render_pdf(data: InvoiceData) -> bytes:
    return _Renderer(data).render()


def _plain_upper(text: str) -> str:
    """Upper case without accents, the way old ERP printouts write labels."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).upper()


class _Renderer:
    def __init__(self, data: InvoiceData) -> None:
        self.data = data
        self.vendor = data.vendor
        self.spec = data.vendor.spec
        self.labels = formats.labels(self.spec)
        self.font = self.spec.font
        self.bold = _BOLD[self.spec.font]
        self.accent = colors.HexColor(self.spec.accent)
        self.page_size: tuple[float, float] = LETTER if self.spec.country == "US" else A4
        self.width = self.page_size[0] - 2 * _MARGIN

    # ----------------------------------------------------------------- formatting

    def money(self, value: Decimal) -> str:
        return formats.money(value, self.spec)

    def num(self, value: Decimal, places: int | None = 2) -> str:
        return formats.number(value, self.spec.number_style, places)

    def day(self, value: Any) -> str:
        return formats.day(value, self.spec)

    def rate(self, value: Decimal) -> str:
        return formats.rate(value, self.spec)

    def quantity(self, line: LineItem, with_unit: bool = True) -> str:
        text = self.num(line.quantity, line.quantity_places)
        return f"{text} {line.unit}" if with_unit and line.unit else text

    def style(
        self,
        size: float = 9,
        *,
        bold: bool = False,
        align: int = TA_LEFT,
        color: colors.Color | None = None,
        leading: float | None = None,
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name=f"s{size}{bold}{align}",
            fontName=self.bold if bold else self.font,
            fontSize=size,
            leading=leading or size * 1.3,
            alignment=align,
            textColor=color or colors.black,
        )

    def para(self, text: str, **style: Any) -> Paragraph:
        """A paragraph of plain text; line breaks in `text` are kept."""
        escaped = html.escape(text, quote=False).replace("\n", "<br/>")
        return Paragraph(escaped, self.style(**style))

    # --------------------------------------------------------------------- content

    @property
    def title(self) -> str:
        return self.labels[self.data.kind]

    @property
    def priced(self) -> bool:
        """A delivery note lists what was shipped, without prices or totals."""
        return self.data.kind != "delivery_note"

    @property
    def number_label(self) -> str:
        if self.data.kind == "invoice":
            return self.labels["number"]
        if self.data.kind == "credit_note":
            return self.labels["credit_number"]
        return self.labels["doc_number"]

    def vat_id_printed(self) -> str:
        vat = self.vendor.vat_id or ""
        if vat.startswith("CHE"):
            return f"CHE-{vat[3:6]}.{vat[6:9]}.{vat[9:12]} MWST"
        if vat.startswith("FR") and self.spec.layout in ("classic", "ledger"):
            return f"FR {vat[2:4]} {vat[4:]}"
        return vat

    def siret_printed(self) -> str:
        siret = self.vendor.siret or ""
        if self.spec.layout == "compact":
            return siret
        return f"{siret[:3]} {siret[3:6]} {siret[6:9]} {siret[9:]}"

    def supplier_ids(self) -> list[str]:
        found = []
        if self.vendor.siret:
            found.append(f"{self.labels['registration']} {self.siret_printed()}")
        if self.vendor.vat_id:
            found.append(f"{self.labels['supplier_vat']} {self.vat_id_printed()}")
        return found

    def buyer_block(self) -> str:
        lines = [COMPANY.name, *COMPANY.address]
        if self.data.show_buyer_vat:
            lines.append(f"{self.labels['customer_vat']} : {COMPANY.vat_id}")
        return "\n".join(lines)

    def meta(self, *, alt: bool = False) -> list[tuple[str, str]]:
        """Label and value of the header fields that are printed on this document."""
        data, labels = self.data, self.labels
        suffix = "_alt" if alt else ""
        pairs = []
        if data.print_number:
            label = labels["number" + suffix] if data.kind == "invoice" else self.number_label
            pairs.append((label, data.number))
        if data.print_issue_date:
            pairs.append((labels["date" + suffix], self.day(data.issue_date)))
        if data.due_date and data.kind in ("invoice", "proforma"):
            pairs.append((labels["due_date" + suffix], self.day(data.due_date)))
        if data.kind == "quote" and data.due_date:
            pairs.append((labels["validity"], self.day(data.due_date)))
        if data.po_number:
            pairs.append((labels["po" + suffix], data.po_number))
        if data.original_invoice:
            pairs.append((labels["original_invoice"], data.original_invoice))
        pairs.append((labels["customer_no"], data.customer_no))
        return pairs

    def meta_without_due_date(self) -> list[tuple[str, str]]:
        due_labels = (self.labels["due_date"], self.labels["due_date_alt"])
        return [pair for pair in self.meta(alt=True) if pair[0] not in due_labels]

    def total_rows(self) -> list[tuple[str, str]]:
        """The totals block, top to bottom. The last row is the amount to pay."""
        data, labels = self.data, self.labels
        rows = []
        if data.allowance or data.charge:
            rows.append((labels["lines_total"], self.money(data.lines_total)))
        if data.allowance:
            label = f"{labels['allowance']} {data.allowance_label}".strip()
            rows.append((label, self.money(-data.allowance)))
        if data.charge:
            rows.append((labels["charge"], self.money(data.charge)))
        rows.append((labels["total_net"], self.money(data.net)))
        for row in data.vat_rows:
            rows.append((f"{labels['vat']} {self.rate(row.rate)}", self.money(row.tax)))
        if len(data.vat_rows) > 1:
            rows.append((labels["total_tax"], self.money(data.tax)))
        rows.append((labels["total_gross"], self.money(data.gross)))
        return rows

    def vat_note(self) -> str | None:
        if self.spec.vat_mode == "reverse_charge":
            return self.labels["reverse_charge"]
        if self.spec.vat_mode == "none":
            return self.labels["no_vat"]
        return None

    def terms(self) -> str:
        if self.spec.terms_days:
            return self.labels["terms_text"].format(days=self.spec.terms_days)
        return self.labels["terms_receipt"]

    def bank_lines(self) -> list[str]:
        data = self.data
        if data.printed_iban:
            lines = [f"IBAN : {ids.spaced(data.printed_iban)}"]
            if data.printed_bic:
                lines.append(f"BIC : {data.printed_bic}")
            return lines
        if self.spec.country == "US":
            return ["First Midwest Bank - ABA routing 071000013 - Account 4417729901"]
        return [self.labels["direct_debit"]]

    def closing_notes(self) -> list[str]:
        """Free text printed under the totals, depending on the kind of document."""
        labels, kind = self.labels, self.data.kind
        notes = list(self.data.notes)
        if note := self.vat_note():
            notes.insert(0, note)
        kind_note = {
            "quote": "quote_note",
            "delivery_note": "delivery_note_note",
            "proforma": "proforma_note",
            "order_confirmation": "order_note",
        }.get(kind)
        if kind_note:
            notes.append(labels[kind_note])
        return notes

    # ---------------------------------------------------------------------- pieces

    def lines_table(
        self,
        columns: list[str],
        widths: list[float],
        *,
        size: float = 8.5,
        grid: bool = False,
        striped: bool = False,
        header_fill: bool = True,
        lines: list[LineItem] | None = None,
        extra_rows: list[list[str]] | None = None,
    ) -> Table:
        """The table of invoice lines.

        `columns` names what each column shows: ref, description, quantity,
        quantity_unit, unit, unit_price, vat, amount, position.
        """
        labels = self.labels
        headers = {
            "ref": "Réf." if self.spec.language == "fr" else "Ref.",
            "position": "Pos.",
            "description": labels["description"],
            "quantity": labels["quantity"],
            "quantity_unit": labels["quantity"],
            "unit": labels["unit"],
            "unit_price": labels["unit_price"],
            "vat": labels["vat_col"],
            "amount": labels["amount"],
        }
        if not self.priced:
            kept = [i for i, column in enumerate(columns) if column not in _PRICE_COLUMNS]
            freed = sum(widths) - sum(widths[i] for i in kept)
            columns, widths = [columns[i] for i in kept], [widths[i] for i in kept]
            widths[columns.index("description")] += freed
            extra_rows = None
        body_style = self.style(size)
        rows: list[list[Any]] = [[headers[column] for column in columns]]
        rows.extend(extra_rows or [])
        for position, line in enumerate(self.data.lines if lines is None else lines, start=1):
            cells = {
                "ref": line.reference,
                "position": str(position),
                "description": Paragraph(html.escape(line.description, quote=False), body_style),
                "quantity": self.quantity(line, with_unit=False),
                "quantity_unit": self.quantity(line),
                "unit": line.unit,
                "unit_price": self.num(line.unit_price, line.price_places),
                "vat": self.rate(line.vat_rate),
                "amount": self.num(line.amount),
            }
            rows.append([cells[column] for column in columns])
        numeric = [i for i, column in enumerate(columns) if column not in ("description", "ref")]
        commands: list[tuple[Any, ...]] = [
            ("FONT", (0, 0), (-1, -1), self.font, size),
            ("FONT", (0, 0), (-1, 0), self.bold, size),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]
        commands += [("ALIGN", (i, 0), (i, -1), "RIGHT") for i in numeric]
        if header_fill:
            commands += [
                ("BACKGROUND", (0, 0), (-1, 0), self.accent),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        else:
            commands.append(("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black))
        if grid:
            commands.append(("GRID", (0, 0), (-1, -1), 0.4, _GREY))
        if striped:
            commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]))
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle(commands))
        return table

    def totals_table(self, width: float = 78 * mm, size: float = 9, boxed: bool = False) -> Table:
        rows = self.total_rows()
        table = Table(rows, colWidths=[width * 0.55, width * 0.45], hAlign="RIGHT")
        commands: list[tuple[Any, ...]] = [
            ("FONT", (0, 0), (-1, -1), self.font, size),
            ("FONT", (0, -1), (-1, -1), self.bold, size + 1),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if boxed:
            commands.append(("BOX", (0, 0), (-1, -1), 0.6, _GREY))
        table.setStyle(TableStyle(commands))
        return table

    def totals_block(self, **options: Any) -> Story:
        return [self.totals_table(**options)] if self.priced else []

    def vat_table(self, size: float = 8.5) -> Table:
        """Rate, taxable base and VAT amount, one row per rate."""
        labels = self.labels
        rows = [[labels["vat_rate"], labels["vat_base"], labels["vat_amount"]]]
        rows += [
            [self.rate(row.rate), self.num(row.base), self.num(row.tax)]
            for row in self.data.vat_rows
        ]
        table = Table(rows, colWidths=[22 * mm, 30 * mm, 30 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, -1), self.font, size),
                    ("FONT", (0, 0), (-1, 0), self.bold, size),
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return table

    def two_columns(self, left: Any, right: Any, split: float = 0.55) -> Table:
        table = Table([[left, right]], colWidths=[self.width * split, self.width * (1 - split)])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return table

    def notes_block(self, size: float = 8) -> Story:
        return [self.para(note, size=size) for note in self.closing_notes()]

    # --------------------------------------------------------------------- layouts

    def render(self) -> bytes:
        if self.data.kind == "reminder":
            story, footer = self._reminder()
        else:
            story, footer = getattr(self, f"_layout_{self.spec.layout}")()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=self.page_size,
            leftMargin=_MARGIN,
            rightMargin=_MARGIN,
            topMargin=_MARGIN,
            bottomMargin=24 * mm,
            title=f"{self.title} {self.data.number}",
            author=self.vendor.name,
            invariant=1,
        )
        hook = self._page_hook(footer)
        document.build(story, onFirstPage=hook, onLaterPages=hook)
        return buffer.getvalue()

    def _page_hook(self, footer: list[str]) -> PageHook:
        data = self.data
        width, height = self.page_size

        def draw(canvas: Canvas, document: Any) -> None:
            canvas.saveState()
            if data.stamp:
                canvas.setFont(self.bold, 64)
                canvas.setFillColor(colors.HexColor("#e5e7eb"))
                canvas.translate(width / 2, height / 2)
                canvas.rotate(35)
                canvas.drawCentredString(0, 0, data.stamp)
                canvas.rotate(-35)
                canvas.translate(-width / 2, -height / 2)
            canvas.setFillColor(_GREY)
            canvas.setFont(self.font, 6.5)
            y = 15 * mm
            for line in reversed(footer):
                canvas.drawCentredString(width / 2, y, line)
                y += 8
            canvas.drawRightString(
                width - _MARGIN, 9 * mm, f"{self.labels['page']} {document.page}"
            )
            if data.hidden_text and document.page == 1:
                # White, tiny text: invisible on paper, present in the text layer.
                canvas.setFillColor(colors.white)
                canvas.setFont(self.font, 1.5)
                y = 30 * mm
                for line in data.hidden_text:
                    canvas.drawString(_MARGIN, y, line)
                    y -= 2
            canvas.restoreState()

        return draw

    def _legal_footer(self, *, with_ids: bool = False) -> list[str]:
        spec = self.spec
        lines = [f"{self.vendor.name} - {', '.join(spec.address[:2])} - {spec.legal}"]
        if with_ids:
            parts = self.supplier_ids()
            if self.data.printed_iban:
                parts.append(f"IBAN {ids.spaced(self.data.printed_iban)}")
                if self.data.printed_bic:
                    parts.append(f"BIC {self.data.printed_bic}")
            lines.append(" - ".join(parts))
        if self.data.is_accounting_document:
            lines.append(self.labels["penalty"])
        return lines

    def _payment(self, size: float = 8.5) -> Story:
        """Payment terms and bank details, printed on accounting documents only."""
        if not self.data.is_accounting_document and self.data.kind != "proforma":
            return []
        labels = self.labels
        text = f"{labels['terms']} : {self.terms()}\n{labels['bank']} : " + " - ".join(
            self.bank_lines()
        )
        return [self.para(text, size=size)]

    def _layout_classic(self) -> tuple[Story, list[str]]:
        spec, labels = self.spec, self.labels
        supplier = [
            self.para(self.vendor.name, size=15, bold=True, color=self.accent, leading=18),
            self.para("\n".join([*spec.address, spec.contact]), size=8.5),
            self.para(" - ".join(self.supplier_ids()), size=8),
        ]
        meta_text = "\n".join(f"{label} : {value}" for label, value in self.meta())
        right = [
            self.para(self.title, size=20, bold=True, align=TA_RIGHT, leading=24),
            Spacer(1, 4),
            self.para(meta_text, size=9.5, align=TA_RIGHT, leading=13.5),
        ]
        buyer = Table(
            [[self.para(f"{labels['customer']} :\n{self.buyer_block()}", size=9.5, leading=13)]],
            colWidths=[80 * mm],
            hAlign="RIGHT",
        )
        buyer.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, _GREY)]))
        columns = ["description", "quantity_unit", "unit_price", "vat", "amount"]
        widths = [self.width - 95 * mm, 22 * mm, 24 * mm, 19 * mm, 30 * mm]
        story: Story = [
            self.two_columns(supplier, right),
            Spacer(1, 8 * mm),
            buyer,
            Spacer(1, 8 * mm),
            self.lines_table(columns, widths, grid=True),
            Spacer(1, 5 * mm),
            *self.totals_block(),
            Spacer(1, 6 * mm),
            *self._payment(),
            Spacer(1, 3 * mm),
            *self.notes_block(),
        ]
        return story, self._legal_footer()

    def _layout_columns(self) -> tuple[Story, list[str]]:
        spec, labels = self.spec, self.labels
        supplier_text = "\n".join(
            [self.vendor.name, *spec.address, *self.supplier_ids(), spec.contact]
        )
        buyer_text = f"{labels['bill_to']}\n{self.buyer_block()}"
        header = self.two_columns(
            self.para(supplier_text, size=9, leading=12.5),
            self.para(buyer_text, size=9, leading=12.5),
            split=0.5,
        )
        meta = self.meta(alt=True)
        meta_table = Table(
            [[label for label, _ in meta], [value for _, value in meta]],
            colWidths=[self.width / len(meta)] * len(meta),
        )
        meta_table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, 0), self.font, 7.5),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _GREY),
                    ("FONT", (0, 1), (-1, 1), self.bold, 9.5),
                    ("LINEABOVE", (0, 0), (-1, 0), 0.8, self.accent),
                    ("LINEBELOW", (0, 1), (-1, 1), 0.8, self.accent),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        columns = ["description", "quantity", "unit", "unit_price", "amount"]
        widths = [self.width - 88 * mm, 20 * mm, 16 * mm, 24 * mm, 28 * mm]
        story: Story = [
            header,
            Spacer(1, 8 * mm),
            self.para(self.title, size=18, bold=True, color=self.accent, leading=22),
            Spacer(1, 3 * mm),
            meta_table,
            Spacer(1, 7 * mm),
            self.lines_table(columns, widths, header_fill=False),
            Spacer(1, 6 * mm),
        ]
        if self.data.is_accounting_document or self.data.kind == "proforma":
            if len(self.data.vat_rows) > 1 or self.spec.amount_style == "bare":
                story += [self.vat_table(), Spacer(1, 3 * mm)]
            story.append(self.totals_table())
            if spec.amount_style == "bare":
                note = labels["amounts_in"].format(currency=spec.currency)
                story.append(self.para(note, size=7.5, align=TA_RIGHT, color=_GREY))
            story += [
                Spacer(1, 6 * mm),
                self.para(labels["bank_intro"], size=8.5, bold=True),
                self.para("\n".join([*self.bank_lines(), self.terms()]), size=8.5),
            ]
        else:
            story += self.totals_block()
        story += [Spacer(1, 4 * mm), *self.notes_block()]
        return story, self._legal_footer()

    def _layout_ledger(self) -> tuple[Story, list[str]]:
        text = "\n".join(self._ledger_lines())
        style = ParagraphStyle("ledger", fontName="Courier", fontSize=8.4, leading=10.6)
        return [Preformatted(text, style)], []

    def _ledger_lines(self) -> list[str]:
        data, spec, labels = self.data, self.spec, self.labels
        width = _LEDGER_WIDTH

        def sides(left: str, right: str = "") -> str:
            return left + " " * max(1, width - len(left) - len(right)) + right

        def dotted(label: str, value: str) -> str:
            return f"{_plain_upper(label)} ".ljust(19, ".") + f": {value}"

        meta = [dotted(label.replace("n°", "numero"), value) for label, value in self.meta()]
        left = [_plain_upper(self.vendor.name), *spec.address, *self.supplier_ids(), spec.contact]
        right = [self.title, *meta]
        out = []
        for index in range(max(len(left), len(right))):
            left_text = left[index] if index < len(left) else ""
            right_text = right[index] if index < len(right) else ""
            out.append(f"{left_text:<52}{right_text}".rstrip())
        buyer = " - ".join([_plain_upper(COMPANY.name), *COMPANY.address[:2]])
        out += ["", f"{_plain_upper(labels['customer'])} : {buyer}"]
        if data.show_buyer_vat:
            out.append(f"{_plain_upper(labels['customer_vat'])} : {COMPANY.vat_id}")
        rule = "-" * width
        heading = (
            f"{_plain_upper(labels['description']):<46}{_plain_upper(labels['quantity']):>10}"
            f"{_plain_upper(labels['unit_price']):>13}{_plain_upper(labels['vat_col']):>9}"
            f"{_plain_upper(labels['amount']):>18}"
        )
        out += ["", rule, heading, rule]
        priced = self.priced
        for line in data.lines:
            row = f"{line.description[:45]:<46}{self.quantity(line, with_unit=False):>10}"
            if priced:
                row += (
                    f"{self.num(line.unit_price, line.price_places):>13}"
                    f"{self.num(line.vat_rate, 1):>9}{self.num(line.amount):>18}"
                )
            out.append(row)
        out.append(rule)
        if priced:
            for label, value in self.total_rows():
                out.append(sides("", f"{_plain_upper(label)} ".ljust(28, ".") + f"{value:>18}"))
        out.append("")
        if data.is_accounting_document:
            out.append(f"{_plain_upper(labels['terms'])} : {self.terms()}")
            out.append(f"{_plain_upper(labels['bank'])} : {' - '.join(self.bank_lines())}")
        out += ["", *self.closing_notes()]
        if data.is_accounting_document:
            out += ["", spec.legal, *_wrap(labels["penalty"], width)]
        if data.hidden_text:
            out.append("")  # hidden lines are drawn by the page hook, not printed here
        return out

    def _layout_anglo(self) -> tuple[Story, list[str]]:
        spec, labels = self.spec, self.labels
        left = [
            self.para(self.vendor.name, size=17, bold=True, color=self.accent, leading=20),
            self.para("\n".join([*spec.address, spec.contact]), size=8.5),
        ]
        right = [self.para(self.title, size=22, bold=True, align=TA_RIGHT, leading=26)]
        meta = self.meta(alt=True)
        meta_table = Table(meta, colWidths=[32 * mm, 42 * mm], hAlign="RIGHT")
        meta_table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (0, -1), self.bold, 9),
                    ("FONT", (1, 0), (1, -1), self.font, 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ]
            )
        )
        bill_to = self.para(f"{labels['bill_to']}:\n{self.buyer_block()}", size=9.5, leading=13)
        columns = ["quantity_unit", "description", "unit_price", "amount"]
        widths = [24 * mm, self.width - 82 * mm, 28 * mm, 30 * mm]
        remit = f"{labels['bank_intro']}:\n" + "\n".join(self.bank_lines())
        story: Story = [
            self.two_columns(left, right, split=0.6),
            Spacer(1, 7 * mm),
            self.two_columns(bill_to, meta_table, split=0.5),
            Spacer(1, 8 * mm),
            self.lines_table(columns, widths, striped=True),
            Spacer(1, 5 * mm),
            *self.totals_block(boxed=True),
            Spacer(1, 7 * mm),
        ]
        if self.data.is_accounting_document or self.data.kind == "proforma":
            story += [
                self.para(f"{labels['terms']}: {self.terms()}", size=9),
                Spacer(1, 2 * mm),
                self.para(remit, size=9),
                Spacer(1, 3 * mm),
            ]
        story += [*self.notes_block(), Spacer(1, 4 * mm), self.para(labels["thanks"], size=9)]
        footer = [f"{self.vendor.name} - {spec.legal}"]
        if self.vendor.vat_id:
            footer.append(f"{labels['supplier_vat']} {self.vat_id_printed()}")
        return story, footer

    def _layout_footer_ids(self) -> tuple[Story, list[str]]:
        labels = self.labels
        wordmark = self.para(
            self.vendor.name.split(" ")[0].upper(),
            size=26,
            bold=True,
            color=self.accent,
            leading=30,
        )
        meta_text = "\n".join(f"{label} : {value}" for label, value in self.meta(alt=True))
        box = Table(
            [
                [self.para(self.title, size=15, bold=True, color=colors.white, leading=19)],
                [self.para(meta_text, size=9, color=colors.white, leading=13)],
            ],
            colWidths=[self.width * 0.42],
        )
        box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), self.accent),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 7),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ]
            )
        )
        columns = ["description", "quantity_unit", "unit_price", "amount"]
        widths = [self.width - 88 * mm, 30 * mm, 28 * mm, 30 * mm]
        story: Story = [
            self.two_columns(wordmark, box, split=0.58),
            Spacer(1, 9 * mm),
            self.para(f"{labels['bill_to']} :\n{self.buyer_block()}", size=9.5, leading=13),
            Spacer(1, 8 * mm),
            self.lines_table(columns, widths, striped=True),
            Spacer(1, 5 * mm),
        ]
        if self.priced:
            if len(self.data.vat_rows) > 1:
                story += [self.vat_table(), Spacer(1, 3 * mm)]
            story.append(self.totals_table())
        story += [Spacer(1, 6 * mm)]
        if self.data.is_accounting_document or self.data.kind == "proforma":
            payment = f"{labels['terms']} : {self.terms()}"
            if not self.data.printed_iban:
                payment += f"\n{' - '.join(self.bank_lines())}"
            story.append(self.para(payment, size=8.5))
        story += [Spacer(1, 3 * mm), *self.notes_block()]
        return story, self._legal_footer(with_ids=True)

    def _layout_german(self) -> tuple[Story, list[str]]:
        spec, labels, data = self.spec, self.labels, self.data
        sender = f"{self.vendor.name} · {' · '.join(spec.address[:2])}"
        info = Table(
            [[f"{label}:", value] for label, value in self.meta_without_due_date()]
            + ([[f"{labels['customer_vat']}:", COMPANY.vat_id]] if data.show_buyer_vat else []),
            colWidths=[34 * mm, 38 * mm],
            hAlign="RIGHT",
        )
        info.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, -1), self.font, 8.5),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        country = {"France": "FRANKREICH"}.get(COMPANY.address[-1], COMPANY.address[-1])
        recipient = "\n".join([COMPANY.name, *COMPANY.address[:-1], country])
        address = [
            self.para(sender, size=6.5, color=_GREY),
            Spacer(1, 2 * mm),
            self.para(recipient, size=10, leading=13.5),
        ]
        heading = f"{labels['number_alt'] if data.kind == 'invoice' else self.title} {data.number}"
        if not data.print_number:
            heading = self.title
        intro = {
            "de": "Sehr geehrte Damen und Herren,\nwir berechnen Ihnen folgende Leistungen:",
        }.get(spec.language, "")
        columns = ["position", "description", "quantity_unit", "unit_price", "amount"]
        widths = [12 * mm, self.width - 98 * mm, 28 * mm, 28 * mm, 30 * mm]
        story: Story = [
            Spacer(1, 22 * mm),
            self.two_columns(address, info, split=0.55),
            Spacer(1, 14 * mm),
            self.para(heading, size=14, bold=True, leading=18),
            Spacer(1, 3 * mm),
            self.para(intro, size=9.5, leading=13),
            Spacer(1, 4 * mm),
            self.lines_table(columns, widths, header_fill=False),
            Spacer(1, 5 * mm),
        ]
        story += [*self.totals_block(), Spacer(1, 7 * mm)]
        if data.is_accounting_document:
            # The due date is only written in a sentence, as German invoices often do.
            sentence = self.terms()
            if data.due_date:
                sentence = f"{labels['due_date_alt']} {self.day(data.due_date)}. {sentence}."
            story.append(self.para(sentence, size=9.5))
        story += [Spacer(1, 3 * mm), *self.notes_block(size=8.5)]
        story += [Spacer(1, 5 * mm), self.para(labels["thanks"], size=9.5)]
        footer = [f"{self.vendor.name} - {', '.join(spec.address[:2])} - {spec.legal}"]
        bank = " - ".join(self.bank_lines()) if data.printed_iban else ""
        footer.append(" - ".join(part for part in (*self.supplier_ids(), spec.contact) if part))
        if bank:
            footer.append(f"{labels['bank']}: {bank}")
        return story, footer

    def _layout_compact(self) -> tuple[Story, list[str]]:
        spec, labels, data = self.spec, self.labels, self.data
        size = 7.6
        supplier = "\n".join([self.vendor.name, *spec.address, *self.supplier_ids(), spec.contact])
        meta_text = "\n".join(f"{label} : {value}" for label, value in self.meta())
        head = Table(
            [
                [
                    self.para(supplier, size=8, leading=10.5),
                    self.para(f"{self.title}\n{meta_text}", size=8.5, bold=True, leading=11.5),
                    self.para(f"{labels['bill_to']}\n{self.buyer_block()}", size=8, leading=10.5),
                ]
            ],
            colWidths=[self.width * 0.36, self.width * 0.32, self.width * 0.32],
        )
        head.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, _GREY),
                ]
            )
        )
        columns = ["ref", "description", "quantity", "unit_price", "vat", "amount"]
        widths = [24 * mm, self.width - 106 * mm, 18 * mm, 22 * mm, 16 * mm, 26 * mm]
        story: Story = [head, Spacer(1, 5 * mm)]
        # Pages are cut by hand so that each one ends with the running total and the next
        # one starts with it, as accounting software prints long invoices.
        first_page, other_pages = 30, 46
        chunks = [data.lines[:first_page]]
        rest = data.lines[first_page:]
        chunks += [rest[i : i + other_pages] for i in range(0, len(rest), other_pages)]
        running = Decimal(0)
        for index, chunk in enumerate(chunks):
            carried = [["", labels["carried"], "", "", "", self.num(running)]] if index else None
            story.append(
                self.lines_table(
                    columns, widths, size=size, grid=True, lines=chunk, extra_rows=carried
                )
            )
            running += sum((line.amount for line in chunk), Decimal(0))
            if index < len(chunks) - 1:
                if self.priced:
                    story.append(
                        self.para(
                            f"{labels['to_carry']} : {self.num(running)}",
                            size=size + 0.5,
                            bold=True,
                            align=TA_RIGHT,
                        )
                    )
                story += [
                    PageBreak(),
                    self.para(
                        f"{self.vendor.name} - {self.title} {data.number}", size=8, bold=True
                    ),
                    Spacer(1, 3 * mm),
                ]
        story.append(Spacer(1, 5 * mm))
        if self.priced:
            story.append(self.two_columns(self.vat_table(size=8), self.totals_table(size=8.5)))
        story += [Spacer(1, 5 * mm), *self._payment(size=8), *self.notes_block(size=7.5)]
        return story, self._legal_footer()

    def _reminder(self) -> tuple[Story, list[str]]:
        """A dunning letter: it names an invoice and an amount, and is not an invoice."""
        spec, labels, data = self.spec, self.labels, self.data
        supplier = "\n".join([self.vendor.name, *spec.address, spec.contact])
        rows = [
            [labels["number"], labels["date"], labels["due_date"], labels["total_gross"]],
            [
                data.original_invoice or "",
                self.day(data.issue_date),
                self.day(data.due_date) if data.due_date else "",
                self.money(data.gross),
            ],
        ]
        table = Table(rows, colWidths=[self.width / 4] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, 0), self.bold, 9),
                    ("FONT", (0, 1), (-1, 1), self.font, 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, _GREY),
                ]
            )
        )
        story: Story = [
            self.two_columns(
                self.para(supplier, size=9, leading=12.5),
                self.para(self.buyer_block(), size=10, leading=13.5),
            ),
            Spacer(1, 14 * mm),
            self.para(self.title, size=15, bold=True, align=TA_CENTER, leading=19),
            Spacer(1, 3 * mm),
            self.para(f"{labels['doc_number']} {data.number}", size=9, align=TA_CENTER),
            Spacer(1, 8 * mm),
            self.para(labels["reminder_note"], size=10, leading=14),
            Spacer(1, 6 * mm),
            table,
            Spacer(1, 6 * mm),
            self.para(" - ".join(self.bank_lines()), size=9),
            *self.notes_block(),
        ]
        return story, self._legal_footer()


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines

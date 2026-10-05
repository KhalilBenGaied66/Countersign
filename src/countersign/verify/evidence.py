"""What the page says, read without any model.

`Evidence` indexes the text layer of a document so that checks can ask two kinds of
question:

- "is this extracted value on the page?" (grounding): a value the model invented or
  computed is not among the numbers, dates and references of the text layer;
- "what does the page contain that the model did not report?" (sweeps): every IBAN,
  every purchase order number, the title of the document and the amounts printed next
  to the label of a total are read by pattern, so that an omission by the model cannot
  hide them.

The text layer is what the file says, which is not always what a person sees: text
drawn in white is in it too. A sweep still finds such text; grounding cannot tell it
from the rest (see docs/security.md).

A scanned document has no text layer and therefore no evidence: `Evidence.of` returns
None, and the pipeline falls back on a second, independent extraction.

Every pattern here runs on text a sender controls: repetitions are bounded so that the
time spent stays proportional to the length of the page.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Literal

from countersign.domain.identifiers import (
    IBAN_LENGTHS,
    IBAN_STRUCTURES,
    compact,
    iban_validity,
)
from countersign.domain.normalize import (
    PrintedNumbers,
    amounts_in,
    currencies_in,
    dates_at,
    dates_in,
    normalize_name,
    normalize_reference,
    printed_numbers,
)

TitleKind = Literal["invoice", "credit_note", "other"]

MAX_REFERENCE_CHARACTERS = 64
# What ties a reference to its neighbour: "FA-2026-0018" followed by "7", "2026-00187"
# preceded by "FA-", "187" followed by ",00" are parts of something longer.
_TIED_BEFORE = r"(?<![^\W_][-/_])"
_TIED_AFTER = r"(?![-/_][^\W_])"
_DIGITS_BEFORE = r"(?<!\d)(?<!\d[.,])"
_DIGITS_AFTER = r"(?!\d)(?![.,]\d)"

# An IBAN starts at a word boundary, or right after its label when the two are glued.
_IBAN_START = re.compile(r"(?:(?<![A-Z0-9])|(?<=IBAN))[A-Z]{2}\d{2}")
# What may separate two characters of a printed IBAN: a space, a dot, a dash, a line break.
_IBAN_GAP = re.compile(r"[ \t]*\n[ \t]*|[ \u00a0\u202f\u2009]{1,2}|[.\-]")
_IBAN_LABEL_REACH = 60

# Titles of documents that are not invoices, then of credit notes, then of invoices, as
# lower-case words without accents. Short words may stand between two words of a title:
# "bon livraison" is found in "Bon de livraison" and not in "bon de commande, adresse de
# livraison".
_OTHER_TITLES = (
    "pro forma",
    "proforma",
    "devis",
    "quotation",
    "quote",
    "bon livraison",
    "delivery note",
    "order confirmation",
    "accuse reception",
    "relance",
    "payment reminder",
    "statement account",
    "releve compte",
    "angebot",
    "lieferschein",
    "zahlungserinnerung",
    "mahnung",
    "auftragsbestatigung",
    "kontoauszug",
    "presupuesto",
    "albaran",
    "recordatorio pago",
    "confirmacion pedido",
    "extracto cuenta",
    "preventivo",
    "documento trasporto",
    "sollecito",
    "conferma ordine",
    "estratto conto",
)
_CREDIT_TITLES = (
    "avoir",
    "note credit",
    "credit note",
    "credit memo",
    "gutschrift",
    "rechnungskorrektur",
    "stornorechnung",
    "rectificativa",
    "nota credito",
)
_INVOICE_TITLES = ("facture", "invoice", "rechnung", "factura", "fattura")
_TITLE_LINES = 15


def _titles(phrases: tuple[str, ...]) -> re.Pattern[str]:
    between = r"[^a-z]{1,3}(?:[a-z]{1,3}[^a-z]{1,3}){0,2}"
    alternatives = "|".join(between.join(phrase.split()) for phrase in phrases)
    return re.compile(rf"(?<![a-z])(?:{alternatives})(?![a-z])")


_TITLES: tuple[tuple[TitleKind, re.Pattern[str]], ...] = (
    ("other", _titles(_OTHER_TITLES)),
    ("credit_note", _titles(_CREDIT_TITLES)),
    ("invoice", _titles(_INVOICE_TITLES)),
)

# Labels that name a total, in the two languages the pipeline was developed on, lower
# case and without accents. The list is a vocabulary, not a rule: a document that uses
# another label, or another language, simply provides no evidence here. A label that
# starts like another one comes first: "total net à payer" is a gross total.
_TOTAL_LABELS: dict[str, tuple[str, ...]] = {
    "total_gross": (
        "total net a payer",
        "total incl. vat",
        "invoice total",
        "net a payer",
        "amount due",
        "total ttc",
        "total due",
    ),
    "total_net": (
        "total hors taxes",
        "total excl. vat",
        "net amount",
        "net total",
        "total net",
        "total ht",
    ),
    "total_tax": ("total tva", "total vat"),
}
# Labels that name a date, in the five languages of the month names.
_DATE_LABELS: dict[str, tuple[str, ...]] = {
    "due_date": (
        "date limite de paiement",
        "fecha de vencimiento",
        "data di scadenza",
        "falligkeitsdatum",
        "date d'echeance",
        "zahlbar bis zum",
        "data scadenza",
        "payment due",
        "zahlbar bis",
        "vencimiento",
        "fallig am",
        "echeance",
        "due date",
        "scadenza",
        "due by",
    ),
    "issue_date": (
        "date de facturation",
        "date de la facture",
        "data di emissione",
        "fecha de emision",
        "fecha de factura",
        "date de facture",
        "date d'emission",
        "rechnungsdatum",
        "date of issue",
        "invoice date",
        "data fattura",
        "issue date",
    ),
}
# What may stand between a label and its date: dot leaders, a colon.
_AFTER_DATE_LABEL = re.compile(r"[ \t.:]{0,60}")


def _labels(vocabulary: dict[str, tuple[str, ...]]) -> re.Pattern[str]:
    groups = "|".join(
        "(?P<{field}>{labels})".format(
            field=field,
            labels="|".join(re.escape(label).replace(r"\ ", r"[ \t]{1,3}") for label in labels),
        )
        for field, labels in vocabulary.items()
    )
    return re.compile(rf"(?<![a-z0-9])(?:{groups})(?![a-z0-9])")


_TOTAL_PATTERN = _labels(_TOTAL_LABELS)
_DATE_PATTERN = _labels(_DATE_LABELS)

# Words of a company name that say nothing about which company it is.
_LEGAL_FORMS = frozenset(
    {"sas", "sasu", "sarl", "sa", "eurl", "sci", "snc", "gmbh", "ag", "kg", "ug", "ltd"}
    | {"limited", "plc", "inc", "llc", "corp", "srl", "spa", "sl", "bv", "nv"}
)


class Evidence:
    def __init__(self, text: str, heading: str = "") -> None:
        self.text = text
        # What the first page prints in large type (see `ParsedDocument.heading`).
        self.heading = heading

    @classmethod
    def of(cls, text: str, *, has_text_layer: bool, heading: str = "") -> "Evidence | None":
        return cls(text, heading) if has_text_layer else None

    @cached_property
    def _alphanumeric(self) -> str:
        return compact(self.text)

    @cached_property
    def _plain_lines(self) -> list[str]:
        """The lines of the page in lower case, without accents."""
        return _plain(self.text).splitlines()

    @cached_property
    def numbers(self) -> PrintedNumbers:
        return printed_numbers(self.text)

    @cached_property
    def dates(self) -> set[date]:
        return dates_in(self.text)

    @cached_property
    def currencies(self) -> set[str]:
        return currencies_in(self.text)

    def has_reference(self, printed: str) -> bool:
        """Whether a reference is printed as a whole, whatever its case and spacing.

        A page that prints "FA-2026-00187" does not print "FA-2026-0018": a number cut
        short would pass for a new invoice, and through duplicate detection. Digits must
        end where the reference ends. Letters need not: text extraction glues a
        neighbouring column to a reference often enough ("PO-2026-00412France").
        """
        characters = [char for char in printed if not char.isspace()]
        if not characters or len(characters) > MAX_REFERENCE_CHARACTERS:
            return False
        body = r"\s*".join(re.escape(char) for char in characters)
        before = _TIED_BEFORE + (_DIGITS_BEFORE if characters[0].isdigit() else "")
        after = _TIED_AFTER + (_DIGITS_AFTER if characters[-1].isdigit() else "")
        return re.search(f"(?i){before}{body}{after}", self.text) is not None

    def has_identifier(self, identifier: str) -> bool:
        """Whether an identifier appears, ignoring spaces, dots and dashes."""
        needle = compact(identifier)
        return bool(needle) and needle in self._alphanumeric

    def has_number(self, value: Decimal, *, whole: bool = False) -> bool:
        """Whether an amount is printed, with its sign.

        `whole` asks for more: that the page delimits this very number, and does not
        only contain it as some digits of a longer one (see `PrintedNumbers`).
        """
        return self.numbers.has(value, whole=whole)

    @cached_property
    def _rows(self) -> list[PrintedNumbers]:
        return [printed_numbers(row) for row in self.text.splitlines() if re.search(r"\d", row)]

    def has_row(self, *values: Decimal) -> bool:
        """Whether one line of the page prints all of `values`.

        The figures of an invoice line stand on one row. An amount that is printed, but
        somewhere else (the net total, reported as the amount of the only line), is not
        the amount of that line.
        """
        return any(all(row.has(value) for value in values) for row in self._rows)

    def has_date(self, value: date) -> bool:
        return value in self.dates

    def has_currency(self, currency: str) -> bool | None:
        """Whether the page names this currency; None when it names none at all."""
        return currency in self.currencies if self.currencies else None

    def names(self, company: str) -> bool:
        """Whether every distinctive word of a company's name is on the page."""
        words = [word for word in normalize_name(company).split() if word not in _LEGAL_FORMS]
        return bool(words) and all(word in self._words for word in words)

    @cached_property
    def _words(self) -> frozenset[str]:
        return frozenset(normalize_name(self.text).split())

    @cached_property
    def ibans(self) -> set[str]:
        """Every account number the page prints in IBAN form, however it is spaced.

        A candidate has the structure its country gives an IBAN. One whose check digits
        are wrong still counts when the page calls it an IBAN: a mistyped account must
        be seen, a VAT number followed by other digits must not.
        """
        text = self.text.upper()
        found: set[str] = set()
        position = 0
        while match := _IBAN_START.search(text, position):
            iban, end = _iban_at(text, match.start())
            if iban is None:
                position = match.start() + 1
                continue
            labelled = "IBAN" in text[max(0, match.start() - _IBAN_LABEL_REACH) : match.start()]
            if labelled or iban_validity(iban) == "valid":
                found.add(iban)
            position = end
        return found

    def references(self, pattern: re.Pattern[str]) -> set[str]:
        """Normalised references matching `pattern`, e.g. the buyer's own PO numbers."""
        return {normalize_reference(match[0]) for match in pattern.finditer(self.text)}

    def labelled_amounts(self, field: str) -> set[Decimal]:
        """Amounts printed on a line after a known label of a total; empty if none.

        Everything between the label and the next label, or the end of the line, is
        looked at: "Total TVA 20 % ..... 245,32" carries 245.32. Values are unsigned.
        """
        found: set[Decimal] = set()
        for line in self._plain_lines:
            matches = list(_TOTAL_PATTERN.finditer(line))
            for index, match in enumerate(matches):
                if match.lastgroup != field:
                    continue
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                found |= amounts_in(line[match.end() : end])
        return found

    def labelled_dates(self, field: str) -> set[date]:
        """Dates printed right after a known label of `field`; empty if none.

        A numeric date that can be read two ways is returned under both readings.
        """
        found: set[date] = set()
        for line in self._plain_lines:
            for match in _DATE_PATTERN.finditer(line):
                if match.lastgroup == field:
                    start = _AFTER_DATE_LABEL.match(line, match.end())
                    found.update(dates_at(line, start.end() if start else match.end()))
        return found

    @cached_property
    def title_kind(self) -> TitleKind | None:
        """What the document calls itself, or None if it carries no known title.

        A title is what the first page prints in large type. A page printed in a single
        size has none of that: its title is then looked for among the first lines, as a
        column written in capitals that starts with a known title.
        """
        kind = _title_in(_plain(self.heading))
        if kind is not None:
            return kind
        lines = [line for line in self.text.splitlines() if line.strip()][:_TITLE_LINES]
        for line in lines:
            for cell in re.split(r"\s{2,}|\t", line.strip()):
                if not _in_capitals(cell):
                    continue
                plain = _plain(cell)
                if any(pattern.match(plain) for _, pattern in _TITLES):
                    return _title_in(plain)
        return None


def _iban_at(text: str, start: int) -> tuple[str | None, int]:
    """The IBAN printed from `start` on, with the position after it; None if there is none."""
    country = text[start : start + 2]
    length = IBAN_LENGTHS.get(country)
    if length is None:
        return None, start
    characters: list[str] = []
    index = start
    while len(characters) < length and index < len(text):
        char = text[index]
        if char.isascii() and char.isalnum():
            characters.append(char)
            index += 1
            continue
        gap = _IBAN_GAP.match(text, index)
        if gap is None:
            break
        index = gap.end()
        if index >= len(text) or not (text[index].isascii() and text[index].isalnum()):
            break
    candidate = "".join(characters)
    if len(candidate) == length and IBAN_STRUCTURES[country].fullmatch(candidate):
        return candidate, index
    return None, start


def _title_in(plain: str) -> TitleKind | None:
    """The kind of document a text in lower case names: not an invoice wins over the rest."""
    for kind, pattern in _TITLES:
        if pattern.search(plain):
            return kind
    return None


def _in_capitals(cell: str) -> bool:
    letters = [char for char in cell if char.isalpha()]
    return len(letters) > 1 and all(char.isupper() for char in letters)


def _plain(text: str) -> str:
    """Lower case, no accents, straight apostrophes; line breaks are kept."""
    decomposed = unicodedata.normalize("NFKD", text.replace("\u2019", "'"))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()

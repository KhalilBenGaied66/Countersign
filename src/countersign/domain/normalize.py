"""Turn the strings printed on an invoice into numbers, dates and identifiers.

Models are asked to copy values as printed; everything here is deterministic. Two
conventions cannot be read from a single value and are passed in as hints:

- the decimal separator: "1.250" is 1250 on a German invoice and 1.25 on a British one;
- the order of day and month: "03/04/2026" is 3 April in Europe and 4 March in the US.

`countersign.pipeline.normalise` infers both from the whole document.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

DecimalSeparator = Literal[",", "."]

# Spaces used as thousands separators: regular, no-break, narrow no-break, thin.
_SPACES = " \u00a0\u202f\u2009"
_GROUPING = _SPACES + "'\u2019"
_MINUS = "-\u2212\u2013"  # hyphen-minus, minus sign, en dash
_NUMBER = re.compile(rf"\d(?:[\d.,{_GROUPING}]*\d)?")
_PLAIN_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SPACE_GROUPED_NUMBER = re.compile(
    rf"(?<![\d.,])\d{{1,3}}(?:[{_GROUPING}]\d{{3}})+(?:[.,]\d+)?(?!\d)"
)
_AMOUNT_NOISE = re.compile(r"(?i)\b(?:eur|euros?|usd|gbp|chf|ttc|ht)\b|[€$£%]")
# A printed number is short. Anything longer is not an amount, and arithmetic on it
# would cost time and memory out of proportion to the document.
MAX_NUMBER_CHARACTERS = 24
MAX_PRINTED_AMOUNT_CHARACTERS = 64
# What the amount columns of the database hold.
MAX_AMOUNT = Decimal(10) ** 12

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}
_CURRENCY_WORDS = {
    "EURO": "EUR",
    "EUROS": "EUR",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "US$": "USD",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "FRANCS": "CHF",
}
KNOWN_CURRENCIES = frozenset({"EUR", "USD", "GBP", "CHF", "SEK", "DKK", "NOK", "PLN", "CAD"})
_CURRENCY_MARK = re.compile(
    r"[€$£]|(?<![A-Za-z])(?:"
    + "|".join(sorted(KNOWN_CURRENCIES))
    + r")(?![A-Za-z])|(?i:\b(?:euros?|dollars?|pounds?)\b)"
)

_MONTHS: dict[str, int] = {}
for _number, _names in enumerate(
    (
        "janvier janv jan january januar enero ene gennaio gen",
        "fevrier fevr fev february feb februar febrero febbraio",
        "mars mar march marz maerz mrz marzo",
        "avril avr april apr abril abr aprile",
        "mai may mayo maggio mag",
        "juin june jun juni junio giugno giu",
        "juillet juil july jul juli julio luglio lug",
        "aout august aug agosto ago",
        "septembre sept sep september septiembre settembre set",
        "octobre oct october oktober okt octubre ottobre ott",
        "novembre nov november noviembre",
        "decembre dec december dezember dez diciembre dic dicembre",
    ),
    start=1,
):
    for _name in _names.split():
        _MONTHS[_name] = _number

# The guards keep a date from being cut out of a longer run of digits: without them
# "2026-03-14" would also be read as the two-digit-year date "26-03-14". Every repetition
# is bounded, and a month name can only start where a word starts: these patterns run on
# page text, which a sender controls, and must stay linear in its length.
_ISO_DATE = re.compile(r"(?<![\d./-])(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUMERIC_DATE = re.compile(
    r"(?<![\d./-])(\d{1,2})\s{0,2}([./-])\s{0,2}(\d{1,2})\s{0,2}[./-]\s{0,2}(\d{4}|\d{2})(?!\d)"
)
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})(?:er|st|nd|rd|th|\.)?[\s-]{1,3}(?:de\s{1,2})?([a-z]{3,10})\.?,?"
    r"[\s-]{1,3}(?:de\s{1,2})?(\d{4})"
)
_MONTH_DAY_YEAR = re.compile(
    r"(?<![a-z])([a-z]{3,10})\.?\s{1,3}(\d{1,2})(?:st|nd|rd|th)?,?\s{1,3}(\d{4})"
)
_DATE_PATTERNS = (_ISO_DATE, _NUMERIC_DATE, _DAY_MONTH_YEAR, _MONTH_DAY_YEAR)
# Dates an invoice can carry. A year outside this range is a misreading, and some of
# them cannot be stored or added to.
MIN_YEAR, MAX_YEAR = 1990, 2100


def _strip_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def parse_amount(raw: str, decimal_separator: DecimalSeparator | None = None) -> Decimal | None:
    """Read the one number printed in `raw`: "1 234,56 €", "(12.50)", "464,60-", "12 pcs".

    Returns None when `raw` holds no number, several numbers, an impossible grouping
    such as "1,23,4", or a number no invoice prints (more than 24 characters, a million
    millions and more). Words around the number (a unit, a label) are ignored: whether
    the value is the right one is for the checks to say, not for the parser.
    `decimal_separator` only matters for the ambiguous shape of one separator followed by
    exactly three digits; without a hint that shape is read as thousands, the common
    case for money.
    """
    if len(raw) > MAX_PRINTED_AMOUNT_CHARACTERS:
        return None
    text = _AMOUNT_NOISE.sub(" ", raw).strip()
    tokens = _NUMBER.findall(text)
    if len(tokens) != 1:
        return None
    token = tokens[0]
    before, _, after = text.partition(token)
    before, after = before.rstrip(), after.lstrip()
    negative = (
        (before.endswith("(") and after.startswith(")"))
        or (bool(before) and before[-1] in _MINUS)
        or (bool(after) and after[0] in _MINUS)
    )
    value = _value(token, decimal_separator)
    if value is None:
        return None
    return -value if negative else value


def _value(token: str, hint: DecimalSeparator | None) -> Decimal | None:
    """The unsigned value of one printed number, or None if it is not one."""
    if len(token) > MAX_NUMBER_CHARACTERS:
        return None
    digits = _to_decimal_string(token, hint)
    if digits is None:
        return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return value if value < MAX_AMOUNT else None


def _to_decimal_string(token: str, hint: DecimalSeparator | None) -> str | None:
    """Rewrite a printed number with "." as the decimal separator and no grouping."""
    groups = re.split(f"[{_GROUPING}]", token)
    if len(groups) > 1:
        # Thousands grouped by spaces or apostrophes: "1 234 567,89", "1'234.56".
        *leading, last = groups
        match = re.fullmatch(r"(\d{3})(?:[.,](\d+))?", last)
        if not match or not re.fullmatch(r"\d{1,3}", leading[0]):
            return None
        if not all(re.fullmatch(r"\d{3}", group) for group in leading[1:]):
            return None
        integer = "".join(leading) + match[1]
        return f"{integer}.{match[2]}" if match[2] else integer
    commas, dots = token.count(","), token.count(".")
    if commas and dots:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        grouping = "." if decimal == "," else ","
        integer, _, fraction = token.rpartition(decimal)
        if decimal in integer or not _grouped_correctly(integer, grouping):
            return None
        return f"{integer.replace(grouping, '')}.{fraction}"
    if not commas and not dots:
        return token
    separator = "," if commas else "."
    if token.count(separator) > 1:
        return token.replace(separator, "") if _grouped_correctly(token, separator) else None
    integer, fraction = token.split(separator)
    ambiguous = len(fraction) == 3 and 1 <= len(integer) <= 3 and integer != "0"
    if ambiguous and hint != separator:
        return integer + fraction
    return f"{integer}.{fraction}"


def _grouped_correctly(integer: str, grouping: str) -> bool:
    groups = integer.split(grouping)
    return 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])


def decimal_separator_vote(raw: str) -> DecimalSeparator | None:
    """The decimal separator a printed number reveals, or None if it reveals nothing."""
    tokens = _NUMBER.findall(_AMOUNT_NOISE.sub(" ", raw))
    if len(tokens) != 1:
        return None
    token = re.sub(f"[{_GROUPING}]", "", tokens[0])
    if "," in token and "." in token:
        return "," if token.rfind(",") > token.rfind(".") else "."
    separators: tuple[DecimalSeparator, DecimalSeparator] = (",", ".")
    for separator in separators:
        if token.count(separator) == 1:
            fraction = token.split(separator)[1]
            # Exactly three digits may be a thousands group: no evidence either way.
            return separator if len(fraction) != 3 else None
    return None


_HINTS: tuple[DecimalSeparator, DecimalSeparator] = (",", ".")


def _values(token: str) -> set[Decimal]:
    """What one printed number may be worth, under both decimal conventions."""
    return {value for hint in _HINTS if (value := _value(token, hint)) is not None}


class PrintedNumbers:
    """The numbers printed in a text, by how surely each one is printed.

    A number is *whole* when the page delimits it: "12 345,00" yields 12345.00. Its
    groups of digits are *parts* when a plain space separates them, because that space
    may also stand between two columns: 12 and 345.00 are then possible readings, and
    nothing more. An apostrophe or a no-break space never separates two columns, so
    "1'240.00" has no parts: a reading of 240.00 is not on the page.

    Signs are kept apart: 464.60 printed as "-464,60" or "464,60-" is not printed as a
    positive amount. A minus sign followed by a space, or a pair of parentheses, counts
    both ways: "TVA 20 % - 245,32" and "(12,50)" are written by suppliers who mean
    either.
    """

    def __init__(self) -> None:
        self._whole: dict[bool, set[Decimal]] = {False: set(), True: set()}
        self._parts: dict[bool, set[Decimal]] = {False: set(), True: set()}

    def _add(self, values: set[Decimal], signs: tuple[bool, bool], *, whole: bool) -> None:
        positive, negative = signs
        target = self._whole if whole else self._parts
        if positive:
            target[False] |= values
        if negative:
            target[True] |= values

    def has(self, value: Decimal, *, whole: bool = False) -> bool:
        """Whether `value` is printed with its sign; `whole` refuses a part of a number."""
        signs = (False, True) if value == 0 else (value < 0,)
        magnitude = abs(value)
        return any(
            magnitude in self._whole[sign] or (not whole and magnitude in self._parts[sign])
            for sign in signs
        )

    def magnitudes(self, *, whole: bool = False) -> set[Decimal]:
        found = self._whole[False] | self._whole[True]
        return found if whole else found | self._parts[False] | self._parts[True]


_CURRENCY_SIGNS = "€$£"
# What may stand right before a minus sign that belongs to a number.
_BEFORE_MINUS = "(:;=" + _CURRENCY_SIGNS


def _is(char: str, among: str) -> bool:
    return bool(char) and char in among


def _signs(text: str, start: int, end: int) -> tuple[bool, bool]:
    """Whether the number at text[start:end] may be positive, and may be negative."""
    before = text[max(0, start - 4) : start]
    if _is(before[-1:], _CURRENCY_SIGNS):
        before = before[:-1]
    last, earlier = before[-1:], before[-2:-1]
    if _is(last, _MINUS):
        if not earlier or earlier.isspace() or earlier in _BEFORE_MINUS:
            return False, True
        # A dash inside a reference, a range or a date: "FA-2026", "10-12", "2026-03-14".
        return True, False
    if _is(last, _SPACES) and _is(earlier, _MINUS):
        still_earlier = before[-3:-2]
        if not still_earlier or still_earlier.isspace():
            return True, True
    after = text[end : end + 2]
    closes = len(after) == 1 or after[1:].isspace() or after[1:] == ")"
    if _is(after[:1], _MINUS) and closes:
        return False, True
    if text[max(0, start - 1) : start] == "(" and after[:1] == ")":
        return True, True
    return True, False


def printed_numbers(text: str) -> PrintedNumbers:
    """Every number of `text`, under both decimal conventions (see `PrintedNumbers`)."""
    found = PrintedNumbers()
    grouped: list[tuple[int, int, bool]] = []
    for match in _SPACE_GROUPED_NUMBER.finditer(text):
        found._add(_values(match[0]), _signs(text, match.start(), match.end()), whole=True)
        splittable = " " in match[0]
        grouped.append((match.start(), match.end(), splittable))
        if splittable:
            _add_parts(found, text, match)
    position = 0
    for match in _PLAIN_NUMBER.finditer(text):
        while position < len(grouped) and grouped[position][1] <= match.start():
            position += 1
        inside = position < len(grouped) and grouped[position][0] <= match.start()
        if not inside:
            found._add(_values(match[0]), _signs(text, match.start(), match.end()), whole=True)
    return found


def _add_parts(found: PrintedNumbers, text: str, match: re.Match[str]) -> None:
    """Every run of digit groups of a number grouped by plain spaces, short of all of them."""
    groups = [(group.start(), group.end()) for group in re.finditer(r"[^ ]+", match[0])]
    offset = match.start()
    for first in range(len(groups)):
        for last in range(first, len(groups)):
            if first == 0 and last == len(groups) - 1:
                continue
            start, end = offset + groups[first][0], offset + groups[last][1]
            found._add(_values(text[start:end]), _signs(text, start, end), whole=False)


def numbers_in(text: str) -> set[Decimal]:
    """Every unsigned value a number printed in `text` may stand for.

    The set errs on the large side: "12 345,00" yields 12345 as well as 12 and 345.
    """
    return printed_numbers(text).magnitudes()


_TWO_DECIMALS = re.compile(r"[.,]\d{2}$")


def amounts_in(text: str) -> set[Decimal]:
    """Unsigned values of the numbers written as money in `text`, each taken whole.

    Money is a number with two decimals that is not a percentage: on the line
    "Total TVA 20 % 245,32" the amount is 245.32, and on "Total HT 3 articles 2 114,41"
    it is 2114.41, neither 2 nor 114.41.
    """
    matches = [*_SPACE_GROUPED_NUMBER.finditer(text), *_PLAIN_NUMBER.finditer(text)]
    found: set[Decimal] = set()
    covered = 0
    for match in sorted(matches, key=lambda match: (match.start(), -match.end())):
        if match.start() < covered:
            continue
        covered = match.end()
        if not _TWO_DECIMALS.search(match[0]):
            continue
        if text[match.end() :].lstrip(_SPACES).startswith("%"):
            continue
        found |= _values(match[0])
    return found


def _year(text: str) -> int:
    year = int(text)
    return year if len(text) == 4 else 2000 + year


def _build(year: int, month: int, day: int) -> date | None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _candidates(pattern: re.Pattern[str], match: re.Match[str]) -> list[date]:
    if pattern is _ISO_DATE:
        found = _build(int(match[1]), int(match[2]), int(match[3]))
        return [found] if found else []
    if pattern is _NUMERIC_DATE:
        first, separator, second, year = int(match[1]), match[2], int(match[3]), _year(match[4])
        day_first = _build(year, second, first)
        # Dots are a continental convention: "03.04.2026" is never read month-first.
        month_first = None if separator == "." else _build(year, first, second)
        return list(dict.fromkeys(d for d in (day_first, month_first) if d))
    day, name = (match[1], match[2]) if pattern is _DAY_MONTH_YEAR else (match[2], match[1])
    month = _MONTHS.get(name)
    found = _build(int(match[3]), month, int(day)) if month else None
    return [found] if found else []


def date_candidates(raw: str) -> list[date]:
    """The dates `raw` may denote: one, or two for an ambiguous numeric date.

    When two are returned, the first is the day-first reading.
    """
    text = _strip_accents(raw).lower().strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match and (pattern is _ISO_DATE or pattern is _NUMERIC_DATE):
            return _candidates(pattern, match)
        if match and (found := _candidates(pattern, match)):
            return found
    return []


def dates_at(text: str, position: int) -> list[date]:
    """The dates written at `position` of `text`, which must be lower case without accents."""
    for pattern in _DATE_PATTERNS:
        match = pattern.match(text, position)
        if match and (found := _candidates(pattern, match)):
            return found
    return []


def parse_date(raw: str, *, day_first: bool = True) -> date | None:
    candidates = date_candidates(raw)
    if not candidates:
        return None
    if len(candidates) == 1 or day_first:
        return candidates[0]
    return candidates[1]


def day_first_vote(raw: str) -> bool | None:
    """Whether a numeric date can only be read day first (True) or month first (False).

    None when `raw` is not a numeric date, is not a real date under either reading
    (a phone number such as "04.72.00"), or is valid both ways.
    """
    match = _NUMERIC_DATE.search(raw)
    if not match or _ISO_DATE.search(raw):
        return None
    first, separator, second, year = int(match[1]), match[2], int(match[3]), _year(match[4])
    day_first = _build(year, second, first)
    month_first = None if separator == "." else _build(year, first, second)
    if day_first and not month_first:
        return True
    if month_first and not day_first:
        return False
    return None


def day_first_votes_in(text: str) -> list[bool]:
    """The votes of every numeric date with a four-digit year printed in `text`."""
    votes = [
        day_first_vote(match[0])
        for match in _NUMERIC_DATE.finditer(text)
        if len(match[4]) == 4 and MIN_YEAR <= int(match[4]) <= MAX_YEAR
    ]
    return [vote for vote in votes if vote is not None]


def dates_in(text: str) -> set[date]:
    """Every date a date-like expression in `text` may denote."""
    lowered = _strip_accents(text).lower()
    found: set[date] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(lowered):
            found.update(_candidates(pattern, match))
    return found


def normalize_currency(raw: str) -> str | None:
    text = raw.strip()
    if text in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[text]
    upper = text.upper()
    if upper in _CURRENCY_WORDS:
        return _CURRENCY_WORDS[upper]
    return upper if re.fullmatch(r"[A-Z]{3}", upper) else None


def currencies_in(text: str) -> set[str]:
    """The currencies a text names, by symbol, ISO code or word."""
    found = set()
    for match in _CURRENCY_MARK.finditer(text):
        currency = normalize_currency(match[0])
        if currency:
            found.add(currency)
    return found


def normalize_reference(raw: str) -> str:
    """Canonical form of an invoice or order number: upper case, no whitespace."""
    return re.sub(r"\s+", "", raw).upper()


def normalize_name(raw: str) -> str:
    """Company name reduced to comparable words: no accents, case or punctuation."""
    words = re.sub(r"[^a-z0-9]+", " ", _strip_accents(raw).lower()).split()
    return " ".join(words)

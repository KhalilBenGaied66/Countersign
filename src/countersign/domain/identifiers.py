"""Checksums of the identifiers printed on an invoice.

A misread digit in an IBAN or a SIRET almost always breaks its checksum, which makes
these the cheapest independent evidence that a value was read correctly. Only schemes
whose algorithm is public and unambiguous are verified; any other identifier is
checked for its shape and reported as "not verifiable", never as valid.
"""

import re
from typing import Literal

# ISO 13616: what follows the country code and the two check digits, for the countries
# of the single euro payments area, in the notation of the IBAN registry (n digits,
# a letters, c either). The structure is what tells an account number from a VAT number
# followed by other capitals, which has the right length often enough.
_BBAN: dict[str, str] = {
    "AD": "n8 c12",
    "AT": "n16",
    "BE": "n12",
    "BG": "a4 n6 c8",
    "CH": "n5 c12",
    "CY": "n8 c16",
    "CZ": "n20",
    "DE": "n18",
    "DK": "n14",
    "EE": "n16",
    "ES": "n20",
    "FI": "n14",
    "FR": "n10 c11 n2",
    "GB": "a4 n14",
    "GI": "a4 c15",
    "GR": "n7 c16",
    "HR": "n17",
    "HU": "n24",
    "IE": "a4 n14",
    "IS": "n22",
    "IT": "a1 n10 c12",
    "LI": "n5 c12",
    "LT": "n16",
    "LU": "n3 c13",
    "LV": "a4 c13",
    "MC": "n10 c11 n2",
    "MT": "a4 n5 c18",
    "NL": "a4 n10",
    "NO": "n11",
    "PL": "n24",
    "PT": "n21",
    "RO": "a4 c16",
    "SE": "n20",
    "SI": "n15",
    "SK": "n20",
    "SM": "a1 n10 c12",
}
_CLASSES = {"n": r"\d", "a": "[A-Z]", "c": "[A-Z0-9]"}
IBAN_STRUCTURES: dict[str, re.Pattern[str]] = {
    country: re.compile(
        rf"{country}\d\d"
        + "".join(f"{_CLASSES[part[0]]}{{{part[1:]}}}" for part in structure.split())
    )
    for country, structure in _BBAN.items()
}
IBAN_LENGTHS: dict[str, int] = {
    country: 4 + sum(int(part[1:]) for part in structure.split())
    for country, structure in _BBAN.items()
}

_IBAN_SHAPE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}")
# Country prefix followed by 2 to 12 letters or digits covers every EU scheme and GB.
_VAT_SHAPE = re.compile(r"[A-Z]{2}[A-Z0-9]{2,12}")

Validity = Literal["valid", "invalid", "unverifiable"]


def compact(raw: str) -> str:
    """Upper-case `raw` and drop everything that is not a letter or a digit."""
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()


def digits_only(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    # A = 10 ... Z = 35, as ISO 7064 expects.
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97


def iban_validity(iban: str) -> Validity:
    """Validate a compact IBAN: shape, national structure when known, then MOD 97-10."""
    if not _IBAN_SHAPE.fullmatch(iban):
        return "invalid"
    structure = IBAN_STRUCTURES.get(iban[:2])
    if structure is not None and not structure.fullmatch(iban):
        return "invalid"
    return "valid" if _mod97(iban) == 1 else "invalid"


def iban_with_check_digits(country: str, bban: str) -> str:
    """Build the IBAN of a national account number (used to generate test data)."""
    check = 98 - _mod97(f"{country}00{bban}")
    return f"{country}{check:02d}{bban}"


def luhn_is_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def luhn_check_digit(payload: str) -> str:
    """The digit to append to `payload` so that the result passes the Luhn check."""
    for candidate in "0123456789":
        if luhn_is_valid(payload + candidate):
            return candidate
    raise ValueError(f"not a digit string: {payload!r}")


def siren_is_valid(siren: str) -> bool:
    return len(siren) == 9 and luhn_is_valid(siren)


def siret_is_valid(siret: str) -> bool:
    """SIRET = SIREN (9 digits) + establishment number (5 digits), Luhn over all 14.

    La Poste (SIREN 356000000) follows another rule and is treated as invalid here.
    """
    return len(siret) == 14 and luhn_is_valid(siret) and siren_is_valid(siret[:9])


def fr_vat_key(siren: str) -> str:
    """The two-digit key of a French VAT number, derived from the SIREN."""
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def vat_validity(vat_id: str) -> Validity:
    """Validate a compact VAT identifier.

    French numbers are verified against their key. Other countries are only checked
    for their shape: "unverifiable" means "nothing wrong was found", not "correct".
    """
    if not _VAT_SHAPE.fullmatch(vat_id):
        return "invalid"
    if vat_id.startswith("FR"):
        key, siren = vat_id[2:4], vat_id[4:]
        if not (len(siren) == 9 and siren.isdigit() and key.isdigit()):
            # Keys with letters exist for a few old registrations; they cannot be checked.
            return "unverifiable" if len(siren) == 9 and siren.isdigit() else "invalid"
        return "valid" if key == fr_vat_key(siren) and siren_is_valid(siren) else "invalid"
    return "unverifiable"

"""Generate identifiers that pass their checksums.

The verification step rejects an IBAN or a SIRET with a wrong check digit, so synthetic
suppliers need well-formed ones. Every function draws from the `random.Random` it is
given: the same seed always yields the same identifiers.
"""

import random
import string

from countersign.domain.identifiers import fr_vat_key, iban_with_check_digits, luhn_check_digit


def _digits(rng: random.Random, count: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(count))


def _letters(rng: random.Random, count: int) -> str:
    return "".join(rng.choice(string.ascii_uppercase) for _ in range(count))


def siren(rng: random.Random) -> str:
    payload = str(rng.randint(3, 9)) + _digits(rng, 7)
    return payload + luhn_check_digit(payload)


def siret(rng: random.Random, siren_number: str) -> str:
    payload = siren_number + "000" + str(rng.randint(1, 9))
    return payload + luhn_check_digit(payload)


def fr_vat(siren_number: str) -> str:
    return f"FR{fr_vat_key(siren_number)}{siren_number}"


def vat_id(rng: random.Random, country: str) -> str | None:
    """A VAT identifier with the national shape. Only French keys are computed."""
    match country:
        case "DE":
            return "DE" + str(rng.randint(1, 9)) + _digits(rng, 8)
        case "ES":
            return "ES" + rng.choice("ABFG") + _digits(rng, 8)
        case "IT":
            return "IT" + _digits(rng, 11)
        case "GB":
            return "GB" + _digits(rng, 9)
        case "NL":
            return "NL" + _digits(rng, 9) + "B01"
        case "IE":
            return "IE" + _digits(rng, 7) + _letters(rng, 2)
        case "BE":
            return "BE0" + _digits(rng, 9)
        case "CH":
            # Swiss UID, printed as CHE-123.456.789 MWST.
            return "CHE" + _digits(rng, 9)
        case _:
            return None


def iban(rng: random.Random, country: str) -> str | None:
    """An IBAN with valid check digits; None for countries that do not use IBANs."""
    match country:
        case "FR":
            bank, branch, account = _digits(rng, 5), _digits(rng, 5), _digits(rng, 11)
            key = 97 - (89 * int(bank) + 15 * int(branch) + 3 * int(account)) % 97
            bban = f"{bank}{branch}{account}{key:02d}"
        case "DE":
            bban = _digits(rng, 18)
        case "ES":
            bban = _digits(rng, 20)
        case "IT":
            bban = _letters(rng, 1) + _digits(rng, 22)
        case "GB" | "IE":
            bban = _letters(rng, 4) + _digits(rng, 14)
        case "NL":
            bban = _letters(rng, 4) + _digits(rng, 10)
        case "BE":
            bban = _digits(rng, 12)
        case "CH":
            bban = _digits(rng, 17)
        case _:
            return None
    return iban_with_check_digits(country, bban)


def bic(rng: random.Random, country: str) -> str:
    return _letters(rng, 4) + country + _letters(rng, 1) + rng.choice("LPX2") + "XXX"


def spaced(compact_iban: str) -> str:
    """Print an IBAN the usual way, in groups of four."""
    return " ".join(compact_iban[i : i + 4] for i in range(0, len(compact_iban), 4))

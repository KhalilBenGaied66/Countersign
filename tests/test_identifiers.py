import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from countersign.datagen import ids
from countersign.domain.identifiers import (
    compact,
    fr_vat_key,
    iban_validity,
    iban_with_check_digits,
    luhn_check_digit,
    luhn_is_valid,
    siren_is_valid,
    siret_is_valid,
    vat_validity,
)

# Published example accounts, one per country.
VALID_IBANS = [
    "FR76 3000 6000 0112 3456 7890 189",
    "DE89 3704 0044 0532 0130 00",
    "GB82 WEST 1234 5698 7654 32",
    "ES91 2100 0418 4502 0005 1332",
    "IT60 X054 2811 1010 0000 0123 456",
    "BE68 5390 0754 7034",
    "NL91 ABNA 0417 1643 00",
    "CH93 0076 2011 6238 5295 7",
]


@pytest.mark.parametrize("printed", VALID_IBANS)
def test_published_ibans_are_valid(printed: str) -> None:
    assert iban_validity(compact(printed)) == "valid"


@pytest.mark.parametrize("printed", VALID_IBANS)
def test_one_wrong_digit_breaks_the_checksum(printed: str) -> None:
    iban = compact(printed)
    for position in range(4, len(iban)):
        if not iban[position].isdigit():
            continue
        wrong = str((int(iban[position]) + 1) % 10)
        assert iban_validity(iban[:position] + wrong + iban[position + 1 :]) == "invalid"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "FR76",
        "FR7630006000011234567890189X",  # one character too many for France
        "FR763000600001123456789018",  # one too few
        "fr7630006000011234567890189",  # not compacted
        "1234567890123456789012",
        "FRAB30006000011234567890189",
    ],
)
def test_malformed_ibans_are_invalid(value: str) -> None:
    assert iban_validity(value) == "invalid"


def test_two_swapped_digits_break_the_checksum() -> None:
    iban = compact(VALID_IBANS[0])
    swapped = iban[:15] + iban[16] + iban[15] + iban[17:]
    assert swapped != iban
    assert iban_validity(swapped) == "invalid"


def test_check_digits_are_computed_for_a_national_account_number() -> None:
    assert iban_with_check_digits("FR", "30006000011234567890189") == compact(VALID_IBANS[0])


@given(st.integers(min_value=0, max_value=10**8 - 1))
def test_luhn_check_digit_makes_any_payload_valid(number: int) -> None:
    payload = f"{number:08d}"
    assert luhn_is_valid(payload + luhn_check_digit(payload))


def test_luhn_rejects_non_digits() -> None:
    assert not luhn_is_valid("12a4")
    with pytest.raises(ValueError, match="not a digit string"):
        luhn_check_digit("12a4")


def test_siren_and_siret_of_the_insee_example() -> None:
    assert siren_is_valid("732829320")
    assert siret_is_valid("73282932000074")
    assert not siret_is_valid("73282932000075")
    assert not siret_is_valid("7328293200007")
    assert not siren_is_valid("732829321")


def test_french_vat_key() -> None:
    assert fr_vat_key("732829320") == "44"
    assert vat_validity("FR44732829320") == "valid"
    assert vat_validity("FR45732829320") == "invalid"
    # A valid key over a SIREN that fails its own check digit is still wrong.
    assert vat_validity(f"FR{fr_vat_key('732829321')}732829321") == "invalid"


@pytest.mark.parametrize("value", ["DE136695976", "GB512421799", "NL576162899B01", "CHE265684389"])
def test_other_countries_are_checked_for_shape_only(value: str) -> None:
    assert vat_validity(value) == "unverifiable"


@pytest.mark.parametrize(
    "value", ["", "FR", "12345678901", "FR4473282932", "F44732829320", "36-4412907"]
)
def test_malformed_vat_numbers_are_invalid(value: str) -> None:
    assert vat_validity(value) == "invalid"


def test_old_french_keys_with_letters_cannot_be_verified() -> None:
    assert vat_validity("FRAB732829320") == "unverifiable"


@pytest.mark.parametrize("country", ["FR", "DE", "ES", "IT", "GB", "IE", "NL", "BE", "CH"])
def test_generated_identifiers_pass_their_checks(country: str) -> None:
    rng = random.Random(country)
    for _ in range(25):
        iban = ids.iban(rng, country)
        assert iban is not None
        assert iban_validity(iban) == "valid"
        vat = ids.vat_id(rng, country) if country != "FR" else ids.fr_vat(ids.siren(rng))
        assert vat is not None
        assert vat_validity(vat) != "invalid"


def test_generated_french_identifiers_are_fully_valid() -> None:
    rng = random.Random(7)
    for _ in range(50):
        siren = ids.siren(rng)
        assert siren_is_valid(siren)
        assert siret_is_valid(ids.siret(rng, siren))
        assert vat_validity(ids.fr_vat(siren)) == "valid"


def test_countries_without_iban_or_vat() -> None:
    rng = random.Random(1)
    assert ids.iban(rng, "US") is None
    assert ids.vat_id(rng, "US") is None


def test_spaced_groups_an_iban_by_four() -> None:
    assert ids.spaced("FR7630006000011234567890189") == VALID_IBANS[0]

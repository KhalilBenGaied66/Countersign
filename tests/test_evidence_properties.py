"""Properties of the page evidence: whatever the values, however they are written."""

import random
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from countersign.datagen import ids
from countersign.domain.identifiers import IBAN_LENGTHS, IBAN_STRUCTURES, iban_validity
from countersign.domain.normalize import amounts_in, printed_numbers
from countersign.master import reference_pattern
from countersign.verify.evidence import Evidence

COUNTRIES = ["FR", "DE", "ES", "IT", "GB", "IE", "NL", "BE", "CH"]
SEPARATORS = [" ", "-", ".", "\u00a0", ""]
AMOUNTS = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999999.99"), places=2)


def _iban(seed: int, country: str) -> str:
    return ids.iban(random.Random(seed), country) or ""


def _grouped(amount: Decimal, thousands: str, decimal: str) -> str:
    integer, fraction = f"{amount:.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return thousands.join(groups) + decimal + fraction


@given(
    seed=st.integers(min_value=0, max_value=10_000),
    country=st.sampled_from(COUNTRIES),
    separator=st.sampled_from(SEPARATORS),
    lower=st.booleans(),
)
def test_an_account_is_swept_however_it_is_written(
    seed: int, country: str, separator: str, lower: bool
) -> None:
    iban = _iban(seed, country)
    assert iban_validity(iban) == "valid"
    assert len(iban) == IBAN_LENGTHS[country]
    assert IBAN_STRUCTURES[country].fullmatch(iban)
    written = separator.join(iban[index : index + 4] for index in range(0, len(iban), 4))
    page = f"Règlement par virement\nIBAN : {written.lower() if lower else written}\nBIC : AGRIFRPP"
    assert Evidence(page).ibans == {iban}


@given(
    first=st.integers(min_value=0, max_value=10_000),
    second=st.integers(min_value=10_001, max_value=20_000),
    country=st.sampled_from(COUNTRIES),
)
def test_two_accounts_on_one_line_are_both_swept(first: int, second: int, country: str) -> None:
    one, other = _iban(first, country), _iban(second, "FR")
    page = f"Ancien compte {ids.spaced(one)} nouveau compte {ids.spaced(other)} merci"
    assert Evidence(page).ibans == {one, other}


@given(seed=st.integers(min_value=0, max_value=10_000))
def test_a_vat_number_and_a_siret_are_never_an_account(seed: int) -> None:
    rng = random.Random(seed)
    siren = ids.siren(rng)
    siret = ids.siret(rng, siren)
    vat = ids.fr_vat(siren)
    for page in (
        f"SIRET {siret} - N° TVA intracommunautaire {vat}",
        f"TVA {vat} APE 1721A RCS LYON B {siren}",
        f"N° TVA {vat[:2]} {vat[2:4]} {vat[4:]} SIRET {siret[:9]} {siret[9:]}",
    ):
        assert Evidence(page).ibans == set(), page


@given(
    amount=AMOUNTS,
    style=st.sampled_from(
        [(" ", ","), ("\u00a0", ","), ("\u202f", ","), ("'", "."), (".", ","), (",", ".")]
    ),
    negative=st.booleans(),
)
def test_a_printed_amount_is_found_whole_with_its_sign(
    amount: Decimal, style: tuple[str, str], negative: bool
) -> None:
    printed = _grouped(amount, *style)
    page = f"Net à payer      {'-' if negative else ''}{printed} EUR"
    numbers = printed_numbers(page)
    signed = -amount if negative else amount
    assert numbers.has(signed, whole=True)
    assert not numbers.has(-signed)
    assert amount in amounts_in(page)


@given(
    amount=st.decimals(min_value=Decimal("1000.00"), max_value=Decimal("999999.99"), places=2),
    style=st.sampled_from([("\u00a0", ","), ("\u202f", ","), ("'", ".")]),
)
def test_the_end_of_an_amount_is_not_an_amount_of_its_own(
    amount: Decimal, style: tuple[str, str]
) -> None:
    """Grouped by anything but a plain space, a number has no parts."""
    printed = _grouped(amount, *style)
    tail = amount % 1000
    if tail in (amount, 0):
        return
    numbers = printed_numbers(f"Total {printed}")
    assert numbers.has(amount)
    assert not numbers.has(tail)


@given(
    year=st.integers(min_value=2020, max_value=2030),
    sequence=st.integers(min_value=1, max_value=99_999),
    prefix=st.sampled_from(["FA-", "INV-", "F", "", "RE/"]),
    glued=st.sampled_from(["", "France", " - page 1", ". Merci", "\n"]),
)
def test_a_reference_is_on_its_page_and_no_piece_of_it_is(
    year: int, sequence: int, prefix: str, glued: str
) -> None:
    reference = f"{prefix}{year}-{sequence:05d}"
    evidence = Evidence(f"Facture n° {reference}{glued}")
    assert evidence.has_reference(reference)
    assert evidence.has_reference(reference.lower())
    assert not evidence.has_reference(reference[:-1])
    assert not evidence.has_reference(reference[len(prefix) + 1 :])
    assert not evidence.has_reference(f"{sequence:05d}")


@given(
    year=st.integers(min_value=2020, max_value=2030),
    sequence=st.integers(min_value=0, max_value=99_999),
    other=st.integers(min_value=0, max_value=9_999_999),
)
def test_a_numbering_accepts_its_own_numbers_and_refuses_shorter_ones(
    year: int, sequence: int, other: int
) -> None:
    pattern = reference_pattern("FA-2026-00187")
    assert pattern.fullmatch(f"FA-{year}-{sequence:05d}")
    assert not pattern.fullmatch(f"FA-{year}-{sequence % 10_000:04d}")
    assert not pattern.fullmatch(f"{year}-{sequence:05d}")
    digits = reference_pattern("0000187")
    assert bool(digits.fullmatch(f"{other:07d}")) is True
    assert not digits.fullmatch(f"{other % 1_000_000:06d}")

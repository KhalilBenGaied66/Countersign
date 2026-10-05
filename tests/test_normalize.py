from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from countersign.datagen import formats
from countersign.datagen.catalog import VENDORS_BY_KEY
from countersign.domain.normalize import (
    date_candidates,
    dates_in,
    day_first_vote,
    day_first_votes_in,
    decimal_separator_vote,
    normalize_currency,
    normalize_name,
    normalize_reference,
    numbers_in,
    parse_amount,
    parse_date,
)

D = Decimal


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("1 234,56 €", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1'234.56", "1234.56"),
        ("1.234.567,89", "1234567.89"),
        ("12", "12"),
        ("0,125", "0.125"),
        ("1.5", "1.5"),
        ("557,52 EUR", "557.52"),
        ("$1,200.00", "1200.00"),
        ("£0.00", "0.00"),
        ("20 %", "20"),
        ("5,5 %", "5.5"),
        ("19%", "19"),
        ("13,29 h", "13.29"),
        ("12 pcs", "12"),
        ("-464,60", "-464.60"),
        ("464,60-", "-464.60"),
        ("(12.50)", "-12.50"),
        ("- 58,74 €", "-58.74"),
        ("1234,5", "1234.5"),
        ("464.60", "464.60"),
    ],
)
def test_printed_numbers_are_read(printed: str, expected: str) -> None:
    assert parse_amount(printed) == D(expected)


@pytest.mark.parametrize(
    "printed",
    ["", "abc", "n/a", "1,23,4", "12 3 4,50", "3 x 65,00", "1.2.3", "20 % 92,92", "1.234,56,7"],
)
def test_what_is_not_one_number_is_rejected(printed: str) -> None:
    assert parse_amount(printed) is None


def test_one_separator_and_three_digits_needs_the_document_convention() -> None:
    # 1250 on a German invoice, 1.25 on a British one.
    assert parse_amount("1.250") == D("1250")
    assert parse_amount("1.250", ",") == D("1250")
    assert parse_amount("1.250", ".") == D("1.250")
    assert parse_amount("1,250", ",") == D("1.250")
    assert parse_amount("1,250", ".") == D("1250")
    # Not ambiguous: a fraction of three digits after a zero is a fraction.
    assert parse_amount("0.125", ",") == D("0.125")


@pytest.mark.parametrize(
    ("printed", "vote"),
    [
        ("464,60", ","),
        ("1 234,56 €", ","),
        ("1.234,56", ","),
        ("1,234.56", "."),
        ("464.6", "."),
        ("1.250", None),
        ("12", None),
        ("abc", None),
    ],
)
def test_decimal_separator_vote(printed: str, vote: str | None) -> None:
    assert decimal_separator_vote(printed) == vote


AMOUNTS = st.decimals(min_value=D("-9999999.99"), max_value=D("9999999.99"), places=2)


@given(amount=AMOUNTS, style=st.sampled_from(["fr", "en", "de", "ch"]))
def test_an_amount_printed_in_any_style_is_read_back(amount: Decimal, style: str) -> None:
    printed = formats.number(amount, style)
    separator = "," if style in ("fr", "de") else "."
    assert parse_amount(printed, separator) == amount


@given(amount=AMOUNTS, key=st.sampled_from(sorted(VENDORS_BY_KEY)))
def test_a_total_printed_by_any_supplier_is_read_back(amount: Decimal, key: str) -> None:
    spec = VENDORS_BY_KEY[key].spec
    separator = "," if spec.number_style in ("fr", "de") else "."
    assert parse_amount(formats.money(amount, spec), separator) == amount


@given(amount=st.decimals(min_value=D("0.01"), max_value=D("9999999.99"), places=2))
def test_a_printed_amount_is_found_on_the_page(amount: Decimal) -> None:
    for style in ("fr", "en", "de", "ch"):
        page = f"Total HT     {formats.number(amount, style)} EUR\nTVA 20 %"
        assert amount in numbers_in(page)


def test_numbers_on_a_page_cover_both_conventions() -> None:
    found = numbers_in("Filtre 592x592x48   12   18,50   222,00\nTotal 1 234,56 - ref 1.250")
    assert {D("592"), D("48"), D("12"), D("18.50"), D("222.00"), D("1234.56")} <= found
    assert D("1250") in found
    assert D("1.250") in found
    assert D("999") not in found


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("2026-03-14", date(2026, 3, 14)),
        ("2026/03/14", date(2026, 3, 14)),
        ("14/03/2026", date(2026, 3, 14)),
        ("14.03.2026", date(2026, 3, 14)),
        ("14-03-2026", date(2026, 3, 14)),
        ("14/03/26", date(2026, 3, 14)),
        ("14 mars 2026", date(2026, 3, 14)),
        ("1er février 2026", date(2026, 2, 1)),
        ("5 août 2026", date(2026, 8, 5)),
        ("03 déc. 2026", date(2026, 12, 3)),
        ("14 March 2026", date(2026, 3, 14)),
        ("March 14, 2026", date(2026, 3, 14)),
        ("Mar 14, 2026", date(2026, 3, 14)),
        ("Sept. 3, 2026", date(2026, 9, 3)),
        ("14-Mar-2026", date(2026, 3, 14)),
        ("14. März 2026", date(2026, 3, 14)),
        ("14 de marzo de 2026", date(2026, 3, 14)),
        ("14 marzo 2026", date(2026, 3, 14)),
        ("Date : 14/03/2026", date(2026, 3, 14)),
    ],
)
def test_printed_dates_are_read(printed: str, expected: date) -> None:
    assert parse_date(printed) == expected


@pytest.mark.parametrize(
    "printed", ["", "31/02/2026", "13/25/2026", "août 2026", "30 jours", "Net 30"]
)
def test_what_is_not_a_date_is_rejected(printed: str) -> None:
    assert parse_date(printed) is None


def test_an_ambiguous_numeric_date_has_two_readings() -> None:
    assert date_candidates("03/04/2026") == [date(2026, 4, 3), date(2026, 3, 4)]
    assert parse_date("03/04/2026", day_first=True) == date(2026, 4, 3)
    assert parse_date("03/04/2026", day_first=False) == date(2026, 3, 4)
    # Dots are a continental convention: no month-first reading.
    assert date_candidates("03.04.2026") == [date(2026, 4, 3)]
    # Same day and month: one date either way.
    assert date_candidates("05/05/2026") == [date(2026, 5, 5)]


@pytest.mark.parametrize(
    ("printed", "vote"),
    [
        ("14/03/2026", True),
        ("12/31/2026", False),
        ("03/04/2026", None),
        ("03.04.2026", True),
        ("2026-03-14", None),
        ("14 mars 2026", None),
        ("04.72.00", None),  # a phone number, not a date
        ("31/02/2026", None),
    ],
)
def test_day_first_vote(printed: str, vote: bool | None) -> None:
    assert day_first_vote(printed) is vote


def test_votes_on_a_page_ignore_iso_dates_phone_numbers_and_short_years() -> None:
    page = "Tél. 04.72.00.41.18 - Date : 2026-03-14 - due 12/31/2026 - ref 17-10-22"
    assert day_first_votes_in(page) == [False]


def test_an_iso_date_is_not_also_read_as_a_two_digit_year_date() -> None:
    assert dates_in("Issued 2026-03-14") == {date(2026, 3, 14)}


def test_dates_on_a_page() -> None:
    page = "Date : 14/03/2026  Échéance : 13 avril 2026, order of March 2, 2026, paid 03/04/2026"
    assert dates_in(page) == {
        date(2026, 3, 14),
        date(2026, 4, 13),
        date(2026, 3, 2),
        date(2026, 4, 3),
        date(2026, 3, 4),
    }


DATES = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))


@given(value=DATES, key=st.sampled_from(sorted(VENDORS_BY_KEY)))
def test_a_date_printed_by_any_supplier_is_read_back(value: date, key: str) -> None:
    spec = VENDORS_BY_KEY[key].spec
    printed = formats.day(value, spec)
    assert parse_date(printed, day_first=spec.date_style != "mdy_slash") == value
    assert value in dates_in(f"Date: {printed} - Page 1")


@given(issue=DATES, term=st.integers(min_value=1, max_value=90))
def test_an_unambiguous_printed_date_votes_for_its_own_convention(issue: date, term: int) -> None:
    due = issue + timedelta(days=term)
    for value in (issue, due):
        if value.day > 12:
            assert day_first_vote(value.strftime("%d/%m/%Y")) is True
            assert day_first_vote(value.strftime("%m/%d/%Y")) is False


@pytest.mark.parametrize(
    ("printed", "code"),
    [
        ("€", "EUR"),
        ("eur", "EUR"),
        ("Euros", "EUR"),
        ("$", "USD"),
        ("US$", "USD"),
        ("£", "GBP"),
        ("CHF", "CHF"),
    ],
)
def test_currency_codes(printed: str, code: str) -> None:
    assert normalize_currency(printed) == code


def test_unknown_currency_text_is_rejected() -> None:
    assert normalize_currency("xx") is None
    assert normalize_currency("euro zone") is None


def test_references_and_names_are_canonicalised() -> None:
    assert normalize_reference(" fac 2026 0012 ") == "FAC20260012"
    assert (
        normalize_name("ACME Fournitures S.A.R.L. — Lyon (Rhône)")
        == "acme fournitures s a r l lyon rhone"
    )

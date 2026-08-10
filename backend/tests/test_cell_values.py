from datetime import date, datetime

import pytest

from app.parsing.cell_values import parse_supply_date


def test_parses_datetime_as_openpyxl_returns_it():
    assert parse_supply_date(datetime(2026, 8, 1, 12, 30)) == date(2026, 8, 1)


def test_parses_date():
    assert parse_supply_date(date(2026, 8, 1)) == date(2026, 8, 1)


def test_parses_google_sheets_serial_number():
    # UNFORMATTED_VALUE отдаёт дату числом дней от 30.12.1899 — 46235 это 01.08.2026.
    assert parse_supply_date(46235) == date(2026, 8, 1)
    assert parse_supply_date(46235.0) == date(2026, 8, 1)


def test_parses_russian_text_date():
    assert parse_supply_date("01.08.2026") == date(2026, 8, 1)


def test_parses_iso_text_date():
    assert parse_supply_date("2026-08-01") == date(2026, 8, 1)


def test_trims_surrounding_spaces():
    assert parse_supply_date("  01.08.2026 ") == date(2026, 8, 1)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_cell_is_none(empty):
    assert parse_supply_date(empty) is None


@pytest.mark.parametrize("garbage", ["завтра", "32.13.2026", "01/08/2026", True])
def test_unparseable_value_raises(garbage):
    with pytest.raises(ValueError):
        parse_supply_date(garbage)

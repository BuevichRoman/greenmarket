import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, GoogleSheetsParserError
from app.parsing.google_sheets_parser import GoogleSheetsParser


class _FakeRequest:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def execute(self, num_retries=0):
        if self._error:
            raise self._error
        return self._payload


class _FakeValues:
    def __init__(self, value_ranges, error=None):
        self._value_ranges = value_ranges
        self._error = error

    def batchGet(self, spreadsheetId, ranges, valueRenderOption):
        assert valueRenderOption == "UNFORMATTED_VALUE"
        return _FakeRequest({"valueRanges": self._value_ranges}, self._error)


class FakeSheetsResource:
    def __init__(self, sheet_titles, rows_by_title=None, get_error=None, values_error=None):
        self._metadata = {"sheets": [{"properties": {"title": t}} for t in sheet_titles]}
        self._get_error = get_error
        rows_by_title = rows_by_title or {}
        self._values = _FakeValues([{"values": rows_by_title.get(t, [])} for t in sheet_titles], values_error)

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId):
        return _FakeRequest(self._metadata, self._get_error)

    def values(self):
        return self._values


def make_http_error(status: int) -> HttpError:
    response = httplib2.Response({"status": status})
    response.status = status
    return HttpError(response, b"{}")


def test_parses_sheets_into_raw_workbook():
    resource = FakeSheetsResource(
        ["Каталог", "_System"],
        rows_by_title={
            "Каталог": [["SellerProductId", "Цена"], [1, 99.5]],
            "_System": [["TemplateVersion", "1.0"]],
        },
    )

    result = GoogleSheetsParser(resource=resource).parse("sheet-id-1")

    assert result.source == "sheet-id-1"
    assert [s.name for s in result.sheets] == ["Каталог", "_System"]
    assert result.sheets[0].rows == [["SellerProductId", "Цена"], [1, 99.5]]


def test_sheet_index_matches_position():
    resource = FakeSheetsResource(["First", "Second"])

    result = GoogleSheetsParser(resource=resource).parse("sheet-id-2")

    assert [(s.name, s.index) for s in result.sheets] == [("First", 0), ("Second", 1)]


def test_not_found_raises_google_sheets_not_found_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(404))

    with pytest.raises(GoogleSheetsNotFoundError):
        GoogleSheetsParser(resource=resource).parse("missing-sheet")


def test_no_access_raises_google_sheets_access_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(403))

    with pytest.raises(GoogleSheetsAccessError):
        GoogleSheetsParser(resource=resource).parse("private-sheet")


def test_other_api_error_raises_generic_parser_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(500))

    with pytest.raises(GoogleSheetsParserError):
        GoogleSheetsParser(resource=resource).parse("broken-sheet")


def test_values_batch_get_error_is_wrapped_too():
    resource = FakeSheetsResource(["Каталог"], values_error=make_http_error(403))

    with pytest.raises(GoogleSheetsAccessError):
        GoogleSheetsParser(resource=resource).parse("sheet-id-3")


def test_unexpected_exception_does_not_leak_raw():
    class ExplodingResource(FakeSheetsResource):
        def get(self, spreadsheetId):
            raise RuntimeError("network exploded")

    with pytest.raises(GoogleSheetsParserError):
        GoogleSheetsParser(resource=ExplodingResource(["Каталог"])).parse("sheet-id-4")

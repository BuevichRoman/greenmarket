from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.publication.mode import read_mode


def _workbook_with_system_rows(rows: list[list[object]]) -> RawWorkbook:
    return RawWorkbook(
        source="test",
        sheets=[RawSheet(name="_System", index=0, rows=rows)],
    )


def test_no_system_sheet_defaults_to_prod():
    workbook = RawWorkbook(source="test", sheets=[])

    assert read_mode(workbook) == "prod"


def test_missing_mode_row_defaults_to_prod():
    workbook = _workbook_with_system_rows([["TemplateVersion", "1.0"], ["TemplateId", "template-1"]])

    assert read_mode(workbook) == "prod"


def test_mode_test_row_resolves_to_test():
    workbook = _workbook_with_system_rows([["TemplateVersion", "1.0"], ["Mode", "TEST"]])

    assert read_mode(workbook) == "test"


def test_mode_test_row_is_case_insensitive_and_accepts_russian():
    for value in ["test", "Test", "ТЕСТ", "тест"]:
        workbook = _workbook_with_system_rows([["Mode", value]])
        assert read_mode(workbook) == "test", f"value={value!r}"


def test_unrecognized_mode_value_defaults_to_prod():
    # Безопасное направление по умолчанию: опечатка/незнакомое значение не
    # должна случайно перенаправить боевую публикацию в тест (и наоборот
    # тестовую — в бой), см. app/publication/mode.py.
    workbook = _workbook_with_system_rows([["Mode", "БОЙ"]])

    assert read_mode(workbook) == "prod"

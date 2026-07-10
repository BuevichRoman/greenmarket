from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.structure_validator import StructureValidator

CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
]

PRODUCT_GROUPS_HEADER = ["ProductGroupId", "ParentProductGroupId", "Наименование"]
PRODUCTS_HEADER = ["ProductId", "ProductGroupId", "Наименование"]

SYSTEM_ROWS = [
    ["DocumentId", "doc-1"],
    ["DocumentVersion", "1.0"],
    ["PublicationKey", "key-1"],
    ["GeneratedAt", "2026-07-10"],
    ["GeneratedBy", "server"],
    ["CatalogHash", "hash-1"],
]


def make_valid_workbook() -> RawWorkbook:
    return RawWorkbook(
        source="valid.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, [1, "Яблоко", "Овощи", "Прочее", 100, "кг", 5, "", ""]]),
            RawSheet(name="Товарные группы", index=1, rows=[PRODUCT_GROUPS_HEADER, [1, None, "Овощи"]]),
            RawSheet(name="Товарные позиции", index=2, rows=[PRODUCTS_HEADER, [1, 1, "Яблоко"]]),
            RawSheet(name="Инструкция", index=3, rows=[["любой текст, как угодно"]]),
            RawSheet(name="_System", index=4, rows=SYSTEM_ROWS),
        ],
    )


def test_valid_workbook_has_no_errors():
    result = StructureValidator().validate(make_valid_workbook())

    assert result.is_valid
    assert result.errors == []


def replace_sheet(workbook: RawWorkbook, name: str, rows: list[list[object]]) -> RawWorkbook:
    sheets = [
        RawSheet(name=sheet.name, index=sheet.index, rows=rows) if sheet.name == name else sheet
        for sheet in workbook.sheets
    ]
    return RawWorkbook(source=workbook.source, sheets=sheets)


def drop_sheet(workbook: RawWorkbook, name: str) -> RawWorkbook:
    return RawWorkbook(source=workbook.source, sheets=[s for s in workbook.sheets if s.name != name])


def test_missing_sheet_reports_error():
    workbook = drop_sheet(make_valid_workbook(), "Товарные группы")

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("Товарные группы" in e.message for e in result.errors)


def test_wrong_column_header_reports_error():
    bad_header = list(CATALOG_HEADER)
    bad_header[1] = "Имя продавца"  # опечатка вместо "Наименование продавца"
    workbook = replace_sheet(make_valid_workbook(), "Каталог", [bad_header])

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("Наименование продавца" in e.message for e in result.errors)


def test_wrong_column_order_reports_error():
    swapped = list(CATALOG_HEADER)
    swapped[4], swapped[5] = swapped[5], swapped[4]  # Цена <-> Единица продажи
    workbook = replace_sheet(make_valid_workbook(), "Каталог", [swapped])

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("Цена" in e.message for e in result.errors)


def test_missing_required_column_reports_error():
    truncated = CATALOG_HEADER[:4]  # обрывается перед "Цена"
    workbook = replace_sheet(make_valid_workbook(), "Каталог", [truncated])

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("обязательная колонка 'Цена'" in e.message for e in result.errors)


def test_missing_system_field_reports_error():
    rows_without_hash = [row for row in SYSTEM_ROWS if row[0] != "CatalogHash"]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows_without_hash)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("CatalogHash" in e.message for e in result.errors)


def test_unsupported_template_version_reports_error():
    rows = [["DocumentVersion", "2.0"] if row[0] == "DocumentVersion" else row for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("версия шаблона" in e.message for e in result.errors)


def test_instruction_sheet_structure_is_not_checked():
    workbook = replace_sheet(make_valid_workbook(), "Инструкция", [["что угодно", 1, None, "не имеет значения"]])

    result = StructureValidator().validate(workbook)

    assert result.is_valid


def test_empty_publication_key_value_reports_error():
    rows = [["PublicationKey", None] if row[0] == "PublicationKey" else row for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("PublicationKey" in e.message for e in result.errors)


def test_narrow_system_sheet_does_not_crash():
    # значение полностью пустое — вся строка шириной 1, не 2
    rows = [[row[0]] for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid

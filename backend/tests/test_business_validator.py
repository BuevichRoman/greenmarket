from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.business_validator import BusinessValidator

CATALOG_HEADER = [
    "SellerProductId",
    "Название товара",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
]


def make_workbook(catalog_rows: list[list[object]]) -> RawWorkbook:
    return RawWorkbook(source="test", sheets=[RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *catalog_rows])])


def test_unique_seller_product_ids_have_no_error():
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [2, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert result.is_valid


def test_duplicate_seller_product_id_reports_error():
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [1, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert not result.is_valid
    assert any("SellerProductId 1" in e.message for e in result.errors)


def test_new_rows_without_seller_product_id_are_not_duplicates():
    rows = [
        [None, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [None, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert result.is_valid

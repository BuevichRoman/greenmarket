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


CATALOG_HEADER_V23 = CATALOG_HEADER + ["Фото", "Страна происхождения", "Дата поставки", "Артикул продавца"]


def make_workbook(catalog_rows: list[list[object]], header: list[str] | None = None) -> RawWorkbook:
    return RawWorkbook(
        source="test",
        sheets=[RawSheet(name="Каталог", index=0, rows=[header or CATALOG_HEADER, *catalog_rows])],
    )


def make_sku_row(sku: object, name: str = "Товар") -> list[object]:
    return [None, name, "Группа", "Позиция", 10, "кг", 5, "", "", "", "", None, sku]


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


def test_unique_seller_sku_has_no_error():
    rows = [make_sku_row("PROD-1001", "Товар A"), make_sku_row("PROD-1002", "Товар B")]

    result = BusinessValidator().validate(make_workbook(rows, header=CATALOG_HEADER_V23))

    assert result.is_valid


def test_duplicate_seller_sku_reports_error_with_row_numbers():
    # Без этой проверки две строки схлопнулись бы в один товар, и продавец
    # молча потерял бы позицию.
    rows = [make_sku_row("PROD-1001", "Товар A"), make_sku_row("PROD-1001", "Товар B")]

    result = BusinessValidator().validate(make_workbook(rows, header=CATALOG_HEADER_V23))

    assert not result.is_valid
    assert any("PROD-1001" in e.message and "[2, 3]" in e.message for e in result.errors)


def test_rows_without_seller_sku_are_not_duplicates():
    rows = [make_sku_row("", "Товар A"), make_sku_row(None, "Товар B")]

    result = BusinessValidator().validate(make_workbook(rows, header=CATALOG_HEADER_V23))

    assert result.is_valid


def test_seller_sku_duplicates_are_compared_as_strings():
    # Sheets отдаёт 1001 числом, а "1001" строкой — для продавца это один
    # артикул, и дубль обязан находиться.
    rows = [make_sku_row(1001, "Товар A"), make_sku_row("1001", "Товар B")]

    result = BusinessValidator().validate(make_workbook(rows, header=CATALOG_HEADER_V23))

    assert not result.is_valid


def test_book_without_seller_sku_column_is_valid():
    rows = [
        [None, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [None, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert result.is_valid

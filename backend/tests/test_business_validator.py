from sqlalchemy import text

from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.seller_gateway import SellerGateway
from app.validation.business_validator import BusinessValidator

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


def insert_seller(session, *, publication_key: str) -> int:
    result = session.execute(
        text("INSERT INTO Seller (name, current_publication_key) VALUES (:name, :publication_key)"),
        {"name": "Тестовый продавец", "publication_key": publication_key},
    )
    return result.lastrowid


def make_workbook(catalog_rows: list[list[object]], publication_key: str | None) -> RawWorkbook:
    system_rows = [["PublicationKey", publication_key]] if publication_key is not None else []
    return RawWorkbook(
        source="test.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *catalog_rows]),
            RawSheet(name="_System", index=1, rows=system_rows),
        ],
    )


def test_matching_publication_key_has_no_error(session):
    seller_id = insert_seller(session, publication_key="key-current")
    workbook = make_workbook([], publication_key="key-current")

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert result.is_valid


def test_stale_publication_key_reports_error(session):
    seller_id = insert_seller(session, publication_key="key-current")
    workbook = make_workbook([], publication_key="key-old")

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert not result.is_valid
    assert any("PublicationKey" in e.message for e in result.errors)


def test_unique_seller_product_ids_have_no_error(session):
    seller_id = insert_seller(session, publication_key="key-current")
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [2, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]
    workbook = make_workbook(rows, publication_key="key-current")

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert result.is_valid


def test_duplicate_seller_product_id_reports_error(session):
    seller_id = insert_seller(session, publication_key="key-current")
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [1, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]
    workbook = make_workbook(rows, publication_key="key-current")

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert not result.is_valid
    assert any("SellerProductId 1" in e.message for e in result.errors)


def test_new_rows_without_seller_product_id_are_not_duplicates(session):
    seller_id = insert_seller(session, publication_key="key-current")
    rows = [
        [None, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [None, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]
    workbook = make_workbook(rows, publication_key="key-current")

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert result.is_valid


def test_missing_publication_key_field_reports_error(session):
    seller_id = insert_seller(session, publication_key="key-current")
    workbook = make_workbook([], publication_key=None)  # лист _System есть, поля PublicationKey — нет

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert not result.is_valid
    assert any("PublicationKey" in e.message for e in result.errors)


def test_narrow_system_sheet_does_not_crash(session):
    seller_id = insert_seller(session, publication_key="key-current")
    workbook = RawWorkbook(
        source="test.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER]),
            RawSheet(name="_System", index=1, rows=[["PublicationKey"]]),  # значение полностью пустое
        ],
    )

    result = BusinessValidator(SellerGateway(session)).validate(workbook, seller_id)

    assert not result.is_valid

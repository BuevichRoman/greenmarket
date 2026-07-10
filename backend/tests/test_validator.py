from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.seller_gateway import SellerGateway
from app.validation.business_validator import BusinessValidator
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator

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
    ["PublicationKey", "key-current"],
    ["GeneratedAt", "2026-07-10"],
    ["GeneratedBy", "server"],
    ["CatalogHash", "hash-1"],
]


class _RefusesToRun:
    def validate(self, *args, **kwargs):
        raise AssertionError("не должен вызываться, если структура невалидна")


def insert_seller(session, *, publication_key: str) -> int:
    result = session.execute(
        text("INSERT INTO Seller (name, current_publication_key) VALUES (:name, :publication_key)"),
        {"name": "Тестовый продавец", "publication_key": publication_key},
    )
    return result.lastrowid


def make_validator(session) -> Validator:
    return Validator(
        StructureValidator(),
        SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
        BusinessValidator(SellerGateway(session)),
    )


def make_valid_workbook(catalog_row: list[object]) -> RawWorkbook:
    return RawWorkbook(
        source="valid.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, catalog_row]),
            RawSheet(name="Товарные группы", index=1, rows=[PRODUCT_GROUPS_HEADER]),
            RawSheet(name="Товарные позиции", index=2, rows=[PRODUCTS_HEADER]),
            RawSheet(name="Инструкция", index=3, rows=[["текст"]]),
            RawSheet(name="_System", index=4, rows=SYSTEM_ROWS),
        ],
    )


def test_valid_workbook_end_to_end_has_no_errors(session):
    seller_id = insert_seller(session, publication_key="key-current")
    row = [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]
    workbook = make_valid_workbook(row)

    result = make_validator(session).validate(workbook, seller_id)

    assert result.is_valid


def test_structure_errors_stop_semantic_and_business_from_running(session):
    workbook = RawWorkbook(source="broken.xlsx", sheets=[])  # ни одного обязательного листа

    validator = Validator(StructureValidator(), _RefusesToRun(), _RefusesToRun())
    result = validator.validate(workbook, seller_id=1)

    assert not result.is_valid


def with_stale_publication_key(workbook: RawWorkbook) -> RawWorkbook:
    stale_system_rows = [["PublicationKey", "key-stale"] if row[0] == "PublicationKey" else row for row in SYSTEM_ROWS]
    sheets = [
        RawSheet(name="_System", index=sheet.index, rows=stale_system_rows) if sheet.name == "_System" else sheet
        for sheet in workbook.sheets
    ]
    return RawWorkbook(source=workbook.source, sheets=sheets)


def test_combines_semantic_and_business_errors_when_structure_is_valid(session):
    seller_id = insert_seller(session, publication_key="key-current")
    # Наименование продавца пусто (semantic) + PublicationKey не совпадает (business)
    row = [1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]
    workbook = with_stale_publication_key(make_valid_workbook(row))

    result = make_validator(session).validate(workbook, seller_id)

    assert not result.is_valid
    assert any(e.column == "Наименование продавца" for e in result.errors)
    assert any("PublicationKey" in e.message for e in result.errors)

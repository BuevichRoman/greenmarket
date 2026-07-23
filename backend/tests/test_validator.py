from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.business_validator import BusinessValidator
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator

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
    "Фото",
]
PRODUCT_GROUPS_HEADER = ["ProductGroupId", "ParentProductGroupId", "Наименование"]
PRODUCTS_HEADER = ["ProductId", "ProductGroupId", "Наименование"]
SYSTEM_ROWS = [
    ["TemplateVersion", "2.0"],
    ["TemplateId", "template-1"],
]


class _RefusesToRun:
    def validate(self, *args, **kwargs):
        raise AssertionError("не должен вызываться, если структура невалидна")


def make_validator(session) -> Validator:
    return Validator(
        StructureValidator(),
        SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session)),
        BusinessValidator(),
    )


def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid


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
    photo_id = insert_photo(session, s3_key="validator-1.jpg")
    row = [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]
    workbook = make_valid_workbook(row)

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_structure_errors_stop_semantic_and_business_from_running(session):
    workbook = RawWorkbook(source="broken.xlsx", sheets=[])  # ни одного обязательного листа

    validator = Validator(StructureValidator(), _RefusesToRun(), _RefusesToRun())
    result = validator.validate(workbook)

    assert not result.is_valid


def test_combines_semantic_and_business_errors_when_structure_is_valid(session):
    # Название товара пусто (semantic) + дубль SellerProductId (business)
    photo_id = insert_photo(session, s3_key="validator-2.jpg")
    rows = [
        [1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)],
        [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 50, "кг", 5, "", "", str(photo_id)],
    ]
    workbook = RawWorkbook(
        source="valid.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *rows]),
            RawSheet(name="Товарные группы", index=1, rows=[PRODUCT_GROUPS_HEADER]),
            RawSheet(name="Товарные позиции", index=2, rows=[PRODUCTS_HEADER]),
            RawSheet(name="Инструкция", index=3, rows=[["текст"]]),
            RawSheet(name="_System", index=4, rows=SYSTEM_ROWS),
        ],
    )

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Название товара" for e in result.errors)
    assert any("SellerProductId 1" in e.message for e in result.errors)

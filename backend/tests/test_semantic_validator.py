from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.semantic_validator import SemanticValidator

HEADER = [
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


def make_workbook(rows: list[list[object]]) -> RawWorkbook:
    return RawWorkbook(source="test.xlsx", sheets=[RawSheet(name="Каталог", index=0, rows=[HEADER, *rows])])


def make_validator(session) -> SemanticValidator:
    return SemanticValidator(ProductGroupRepository(session), ProductRepository(session))


def test_valid_row_has_no_errors(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_missing_required_field_reports_error(session):
    workbook = make_workbook([[1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Наименование продавца" for e in result.errors)


def test_unknown_product_group_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Несуществующая группа", "Апельсин", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующая группа" in e.message for e in result.errors)


def test_product_from_a_different_group_reports_error(session):
    # "Апельсин" реально существует, но под группой "Цитрусовые", не "Овощи" —
    # идентификация в БД по комбинации ProductGroup + Product
    # (database/migrations/002_create_products.sql), не по одному имени.
    workbook = make_workbook([[1, "Апельсины оптом", "Овощи", "Апельсин", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Апельсин" in e.message for e in result.errors)


def test_unknown_product_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Несуществующий товар", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующий товар" in e.message for e in result.errors)


def test_other_product_placeholder_is_allowed(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Прочее", 99.5, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_negative_price_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", -1, "кг", 10, "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Цена" for e in result.errors)


def test_non_numeric_stock_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", "много", "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Остаток" for e in result.errors)


def test_empty_catalog_sheet_has_no_errors(session):
    workbook = make_workbook([])

    result = make_validator(session).validate(workbook)

    assert result.is_valid

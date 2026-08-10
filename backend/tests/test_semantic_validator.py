from datetime import date, timedelta

from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.semantic_validator import SemanticValidator

HEADER = [
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
    "Страна происхождения",
    "Дата поставки",
]


def make_workbook(rows: list[list[object]]) -> RawWorkbook:
    return RawWorkbook(source="test.xlsx", sheets=[RawSheet(name="Каталог", index=0, rows=[HEADER, *rows])])


def make_validator(session) -> SemanticValidator:
    return SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session))


def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid


def test_valid_row_has_no_errors(session):
    photo_id = insert_photo(session, s3_key="a.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_missing_required_field_reports_error(session):
    photo_id = insert_photo(session, s3_key="b.jpg")
    workbook = make_workbook([[1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Название товара" for e in result.errors)


def test_unknown_product_group_reports_error(session):
    photo_id = insert_photo(session, s3_key="c.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Несуществующая группа", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующая группа" in e.message for e in result.errors)


def test_product_from_a_different_group_reports_error(session):
    # "Апельсин" реально существует, но под группой "Цитрусовые", не "Овощи" —
    # идентификация в БД по комбинации ProductGroup + Product
    # (database/migrations/002_create_products.sql), не по одному имени.
    photo_id = insert_photo(session, s3_key="d.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Овощи", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Апельсин" in e.message for e in result.errors)


def test_unknown_product_reports_error(session):
    photo_id = insert_photo(session, s3_key="e.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Несуществующий товар", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующий товар" in e.message for e in result.errors)


def test_other_product_placeholder_is_allowed(session):
    photo_id = insert_photo(session, s3_key="f.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Прочее", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_negative_price_reports_error(session):
    photo_id = insert_photo(session, s3_key="g.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", -1, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Цена" for e in result.errors)


def test_non_numeric_stock_reports_error(session):
    photo_id = insert_photo(session, s3_key="h.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", "много", "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Остаток" for e in result.errors)


def test_fully_empty_row_is_ignored(session):
    # Google Sheets API отдаёт отформатированные, но незаполненные строки шаблона
    # (dropdown/border без данных) как строки из пустых значений — такая строка не
    # является товаром продавца и не должна порождать ошибки валидации.
    photo_a = insert_photo(session, s3_key="i.jpg")
    photo_b = insert_photo(session, s3_key="j.jpg")
    empty_row = [None] * len(HEADER)
    workbook = make_workbook(
        [
            [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_a)],
            empty_row,
            [2, "Лимоны оптом", "Цитрусовые", "Лимон", 79.0, "кг", 5, "", "", str(photo_b)],
        ]
    )

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_empty_origin_and_supply_date_are_allowed(session):
    """Обе колонки необязательны, и у книги шаблона 2.1 их вовсе нет."""
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "", ""]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_valid_supply_date_has_no_errors(session):
    workbook = make_workbook(
        [[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "Марокко", "01.08.2026"]]
    )

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_unparseable_supply_date_reports_error(session):
    workbook = make_workbook(
        [[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "Марокко", "как-нибудь на днях"]]
    )

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Дата поставки" for e in result.errors)


def test_future_supply_date_reports_error(session):
    """Дата завоза — признак свежести партии, она в прошлом. Дата из будущего
    означает опечатку продавца, а не «поставка ожидается»."""
    tomorrow = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    workbook = make_workbook(
        [[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "Марокко", tomorrow]]
    )

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Дата поставки" for e in result.errors)


def test_today_supply_date_is_allowed(session):
    today = date.today().strftime("%d.%m.%Y")
    workbook = make_workbook(
        [[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "Марокко", today]]
    )

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_too_long_origin_country_reports_error(session):
    workbook = make_workbook(
        [[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "", "Я" * 101, ""]]
    )

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Страна происхождения" for e in result.errors)


def test_empty_catalog_sheet_has_no_errors(session):
    workbook = make_workbook([])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_missing_photo_is_allowed(session):
    # Пустое фото больше не ошибка — строка публикуется, но в каталог покупателя
    # не попадает (is_published=False, см. PublicationService). Битый формат при
    # этом остаётся ошибкой — тесты ниже.
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", ""]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_non_numeric_photo_id_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "not-a-number"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_nonexistent_photo_id_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "999999999"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_multiple_photo_ids_all_must_exist(session):
    photo_a = insert_photo(session, s3_key="k.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", f"{photo_a};999999999"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_multiple_valid_photo_ids_have_no_error(session):
    photo_a = insert_photo(session, s3_key="l.jpg")
    photo_b = insert_photo(session, s3_key="m.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", f"{photo_a};{photo_b}"]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid


def test_duplicate_photo_id_reports_error(session):
    photo_id = insert_photo(session, s3_key="dup.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", f"{photo_id};{photo_id}"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)

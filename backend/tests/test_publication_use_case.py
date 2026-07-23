from sqlalchemy import text

from app.application.publication_use_case import PublicationUseCase, PublicationValidationError
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.publication.errors import DuplicatePublicationError
from tests.test_google_sheets_parser import FakeSheetsResource

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
SYSTEM_ROWS = [["TemplateVersion", "2.0"], ["TemplateId", "template-1"]]


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid


def make_resource(catalog_rows: list[list[object]], system_rows: list[list[object]] | None = None) -> FakeSheetsResource:
    return FakeSheetsResource(
        ["Каталог", "Товарные группы", "Товарные позиции", "Инструкция", "_System"],
        rows_by_title={
            "Каталог": [CATALOG_HEADER, *catalog_rows],
            "Товарные группы": [PRODUCT_GROUPS_HEADER],
            "Товарные позиции": [PRODUCTS_HEADER],
            "Инструкция": [["текст"]],
            "_System": system_rows if system_rows is not None else SYSTEM_ROWS,
        },
    )


def test_publishes_valid_catalog(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма Use Case")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-1.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    result = use_case.publish("sheet-1", seller_id=seller_id, published_by=user_id)

    assert result.success is True
    assert result.created_count == 1
    assert result.publication_id > 0


def test_validation_error_raises_with_error_list(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма невалидная")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-2.jpg")
    # Цена отрицательная — SemanticValidator должен отклонить
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    import pytest
    with pytest.raises(PublicationValidationError) as exc_info:
        use_case.publish("sheet-2", seller_id=seller_id, published_by=user_id)

    assert len(exc_info.value.validation_result.errors) > 0


def test_republishing_same_content_is_idempotent_no_op(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма повтор")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-3.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    first = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)
    second = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)

    assert first.publication_key != second.publication_key  # новый ключ на каждый вызов (CR-001)
    assert (second.created_count, second.updated_count, second.deactivated_count) == (0, 0, 0)


def test_no_mode_row_defaults_to_prod_result(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма без Mode")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-4.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    result = use_case.publish("sheet-mode-default", seller_id=seller_id, published_by=user_id)

    assert result.mode == "prod"


def test_mode_test_writes_to_test_session_not_prod(committing_session, test_committing_session):
    from app.infrastructure.repositories.seller_product_repository import SellerProductRepository

    # seller_id намеренно существует только в тестовой схеме — если бы код
    # ошибочно писал в прод (committing_session), FK на Seller там бы упал.
    seller_id = insert_seller(test_committing_session, name="Ферма TEST-режим")
    user_id = insert_user(test_committing_session, name="Admin")
    photo_id = insert_photo(test_committing_session, s3_key="uc-5.jpg")
    resource = make_resource(
        [[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]],
        system_rows=[*SYSTEM_ROWS, ["Mode", "TEST"]],
    )
    use_case = PublicationUseCase(committing_session, test_committing_session, parser_resource=resource)

    result = use_case.publish("sheet-mode-test", seller_id=seller_id, published_by=user_id)

    assert result.mode == "test"
    assert result.success is True
    seller_products = SellerProductRepository(test_committing_session).list_by_seller(seller_id)
    assert len(seller_products) == 1


def test_mode_test_without_configured_test_session_raises_clear_error():
    from app.publication.errors import TestModeUnavailableError

    resource = make_resource(
        [[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]],
        system_rows=[*SYSTEM_ROWS, ["Mode", "TEST"]],
    )
    use_case = PublicationUseCase(None, None, parser_resource=resource)

    import pytest
    with pytest.raises(TestModeUnavailableError):
        use_case.publish("sheet-mode-unavailable", seller_id=1, published_by=1)

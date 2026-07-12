from sqlalchemy import text

from app.api.v1.publications import get_google_sheets_parser_resource
from app.main import app
from tests.test_google_sheets_parser import FakeSheetsResource, make_http_error

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
SYSTEM_ROWS = [["TemplateVersion", "1.0"], ["TemplateId", "template-1"]]


def insert_seller(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO Seller (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO User (name) VALUES (:name)"), {"name": name}).lastrowid


def make_resource(catalog_rows, **overrides) -> FakeSheetsResource:
    return FakeSheetsResource(
        ["Каталог", "Товарные группы", "Товарные позиции", "Инструкция", "_System"],
        rows_by_title={
            "Каталог": [CATALOG_HEADER, *catalog_rows],
            "Товарные группы": [PRODUCT_GROUPS_HEADER],
            "Товарные позиции": [PRODUCTS_HEADER],
            "Инструкция": [["текст"]],
            "_System": SYSTEM_ROWS,
        },
        **overrides,
    )


def override_session(committing_session):
    from app.infrastructure.database import get_session

    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def override_resource(resource):
    app.dependency_overrides[get_google_sheets_parser_resource] = lambda: resource


def test_successful_publication_returns_200(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма API")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-1"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["created"] == 1


def test_missing_sheet_source_returns_422(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма без ссылки")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/publications", json={"seller_id": seller_id, "published_by": user_id})

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validation_errors_return_422_with_details(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-2"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert len(response.json()["error"]["details"]) > 0


def test_sheet_not_found_returns_400(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма таблица не найдена")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([], get_error=make_http_error(404)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-3"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SHEET_NOT_FOUND"


def test_spreadsheet_id_is_extracted_from_sheet_url(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ссылка")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={
            "seller_id": seller_id,
            "published_by": user_id,
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-api-4/edit#gid=0",
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200

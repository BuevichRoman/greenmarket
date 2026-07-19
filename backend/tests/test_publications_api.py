from sqlalchemy import text

from app.api.v1.publications import get_google_sheets_parser_resource, get_seller_access_resolver
from app.main import app
from app.publication.seller_access import SellerAccess
from tests.test_google_sheets_parser import FakeSheetsResource, make_http_error

VALID_TOKEN = "test-token"


def override_seller_access(seller_id: int, published_by: int, *, name: str = "Тестовый продавец") -> None:
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name=name)
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: access if token == VALID_TOKEN else None)

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
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


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
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-1"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["created"] == 1


def test_missing_or_invalid_access_token_returns_403(committing_session):
    # Регрессия на дыру безопасности: раньше клиент сам присылал seller_id/
    # published_by открытым текстом — любой мог опубликовать каталог от имени
    # чужого продавца. Теперь единственный путь — access_token, который
    # резолвится сервером; неизвестный токен обязан быть отклонён.
    from fastapi.testclient import TestClient

    override_session(committing_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": "not-a-real-token", "spreadsheet_id": "sheet-api-security"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_missing_sheet_source_returns_422(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма без ссылки")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    client = TestClient(app)

    response = client.post("/api/v1/publications", json={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_pydantic_type_error_returns_422_with_envelope(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": 12345, "spreadsheet_id": "x"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validation_errors_return_422_with_details(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-2"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert len(response.json()["error"]["details"]) > 0


def test_validation_errors_include_sheet_row_column(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации 2")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-8"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]
    assert detail["sheet"] == "Каталог"
    assert detail["row"] == 2
    assert detail["column"] == "Цена"
    assert "отрицательным" in detail["message"]


def test_sheet_not_found_returns_404(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма таблица не найдена")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([], get_error=make_http_error(404)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-3"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHEET_NOT_FOUND"


def test_sheet_access_denied_returns_403(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма доступ запрещён")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([], get_error=make_http_error(403)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-5"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SHEET_ACCESS_DENIED"


def test_generic_google_api_error_returns_500(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка API")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([], get_error=make_http_error(500)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-6"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "GOOGLE_API_ERROR"


def test_unexpected_construction_failure_returns_500_internal_error(committing_session, monkeypatch):
    # Не переопределяем get_google_sheets_parser_resource — PublicationUseCase
    # строит настоящий GoogleSheetsParser, который должен упасть при сборке
    # Service Account credentials. Раньше тест полагался на то, что
    # settings.google_service_account_file случайно указывает на
    # несуществующий файл — ложилось на состояние диска разработчика, а не на
    # тест: после реального деплоя ТЗ-010 файл реально появился в backend/, и
    # тест начал молча проверять другой путь (404 от Google API вместо сбоя
    # конструктора). Патчим путь явно, чтобы падение было детерминированным
    # независимо от того, что лежит на диске.
    #
    # Регрессионный тест на фикс "конструктор PublicationUseCase внутри try":
    # без него сюда бы утекло сырое исключение вместо конверта {"error": ...}.
    from fastapi.testclient import TestClient

    from app.core.config import settings

    monkeypatch.setattr(settings, "google_service_account_file", "/nonexistent/google-service-account.json")

    seller_id = insert_seller(committing_session, name="Ферма сбой конструктора")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"access_token": VALID_TOKEN, "spreadsheet_id": "sheet-api-7"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "google-service-account" not in body["error"]["message"]
    assert ".json" not in body["error"]["message"]


def test_spreadsheet_id_is_extracted_from_sheet_url(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ссылка")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={
            "access_token": VALID_TOKEN,
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-api-4/edit#gid=0",
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200

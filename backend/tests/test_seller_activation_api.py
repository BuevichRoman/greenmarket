from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app
from app.publication.seller_activation import issue_activation_code


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def test_activate_returns_access_token_for_valid_code(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец для API-активации")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-api-1"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["access_token"]) > 20


def test_activate_rejects_unknown_code(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/seller/activate", json={"activation_code": "not-a-real-code", "spreadsheet_id": "sheet-x"}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_CODE"


def test_activate_rejects_reused_code(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец для повторного кода")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    first = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-first"})
    assert first.status_code == 200

    second = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-second"})

    app.dependency_overrides.clear()
    assert second.status_code == 400


def test_activated_token_resolves_via_seller_catalog_endpoint(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец сквозной проверки")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)

    activate_response = client.post(
        "/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-e2e"}
    )
    token = activate_response.json()["access_token"]

    status_response = client.get("/api/v1/seller/catalog", params={"access_token": token})

    app.dependency_overrides.clear()
    assert status_response.status_code == 200
    assert status_response.json()["seller_id"] == seller_id

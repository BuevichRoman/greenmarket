from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin.admin_activation import issue_admin_activation_code
from app.infrastructure.database import get_session
from app.main import app


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def admin_headers(session, client, *, name: str) -> dict[str, str]:
    user_id = insert_user(session, name=name)
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_seller_returns_seller_id_and_activation_code(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ онбординга")
    user_id = insert_user(committing_session, name="Фермер через API")

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] > 0
    assert body["activation_code"]


def test_create_seller_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    user_id = insert_user(committing_session, name="Фермер без админа")

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id})

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"
    assert committing_session.execute(
        text("SELECT COUNT(*) FROM Seller WHERE user_id = :id"), {"id": user_id}
    ).scalar() == 0


def test_create_seller_rejects_unknown_platform_user(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестного юзера")

    response = client.post("/api/v1/admin/sellers", json={"user_id": 999_999_999}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_create_seller_rejects_duplicate(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ дубля")
    user_id = insert_user(committing_session, name="Фермер дубль")
    first = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELLER_ALREADY_EXISTS"
    # seller_id существующего продавца должен быть в сообщении — иначе админу
    # некуда идти за перевыпуском кода.
    assert str(first.json()["seller_id"]) in response.json()["error"]["message"]


def test_reissue_activation_code_replaces_previous_one(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ перевыпуска")
    user_id = insert_user(committing_session, name="Фермер перевыпуск")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.post(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["activation_code"] != created["activation_code"]


def test_reissue_activation_code_rejects_unknown_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ несуществующего продавца")

    response = client.post("/api/v1/admin/sellers/999999/activation-code", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_revoke_activation_code_makes_it_unusable(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ отзыва")
    user_id = insert_user(committing_session, name="Фермер отзыв")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.delete(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code", headers=headers)

    assert response.status_code == 204
    activation = client.post(
        "/api/v1/seller/activate",
        json={"activation_code": created["activation_code"], "spreadsheet_id": "sheet-revoked"},
    )
    app.dependency_overrides.clear()
    assert activation.status_code == 400


def test_revoke_activation_code_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ отзыва без токена")
    user_id = insert_user(committing_session, name="Фермер отзыв без токена")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.delete(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code")

    app.dependency_overrides.clear()
    assert response.status_code == 401

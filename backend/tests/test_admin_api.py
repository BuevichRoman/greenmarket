from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin.admin_activation import issue_admin_activation_code
from app.infrastructure.database import get_session
from app.main import app


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_admin(session, *, name: str) -> tuple[int, int]:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return admin_id, user_id


def test_activate_returns_access_token_for_valid_code(committing_session):
    admin_id, _ = insert_admin(committing_session, name="Админ для API-активации")
    code = issue_admin_activation_code(admin_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/admin/activate", json={"activation_code": code})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["access_token"]) > 20


def test_activate_rejects_unknown_code(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/admin/activate", json={"activation_code": "not-a-real-code"})

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_CODE"


def test_activate_rejects_reused_code(committing_session):
    admin_id, _ = insert_admin(committing_session, name="Админ для повторного кода")
    code = issue_admin_activation_code(admin_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    first = client.post("/api/v1/admin/activate", json={"activation_code": code})
    assert first.status_code == 200

    second = client.post("/api/v1/admin/activate", json={"activation_code": code})

    app.dependency_overrides.clear()
    assert second.status_code == 400


def test_activated_token_resolves_via_me_endpoint(committing_session):
    admin_id, user_id = insert_admin(committing_session, name="Админ сквозной проверки")
    code = issue_admin_activation_code(admin_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]

    response = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"admin_id": admin_id, "user_id": user_id}


def test_me_rejects_request_without_authorization_header(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/me")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_me_rejects_unknown_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/me", headers={"Authorization": "Bearer nonsense-token"})

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_me_rejects_valid_token_passed_as_query_parameter(committing_session):
    """Токен администратора принимается только в заголовке: query-строка целиком
    пишется в access.log nginx, а у админа права на модерацию всего каталога."""
    admin_id, _ = insert_admin(committing_session, name="Админ токен в query")
    code = issue_admin_activation_code(admin_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]

    response = client.get("/api/v1/admin/me", params={"access_token": token})

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_me_rejects_token_of_deactivated_admin(committing_session):
    admin_id, _ = insert_admin(committing_session, name="Отозванный админ API")
    code = issue_admin_activation_code(admin_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    committing_session.execute(text("UPDATE Administrator SET is_active = FALSE WHERE id = :id"), {"id": admin_id})

    response = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"})

    app.dependency_overrides.clear()
    assert response.status_code == 401

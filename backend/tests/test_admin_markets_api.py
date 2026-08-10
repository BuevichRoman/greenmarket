"""Admin API справочника рынков (миграция 017).

Рынки заводит администратор: адрес и координаты — данные рынка, а не продавца,
и один и тот же рынок обслуживает сотни продавцов (Seller_Profile.md, §3).
Продавец рынок только выбирает из списка (`GET /api/v1/seller/markets`).
"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin.admin_activation import issue_admin_activation_code
from app.infrastructure.database import get_session
from app.main import app


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def admin_headers(session, client, *, name: str) -> dict[str, str]:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def setup(committing_session, *, name: str) -> tuple[TestClient, dict[str, str]]:
    override_session(committing_session)
    client = TestClient(app)
    return client, admin_headers(committing_session, client, name=name)


def test_create_market_with_coordinates(committing_session):
    client, headers = setup(committing_session, name="Админ рынков 1")

    response = client.post(
        "/api/v1/admin/markets",
        json={
            "name": "Даниловский рынок",
            "address": "Москва, Мытная, 74",
            "latitude": "55.7150000",
            "longitude": "37.6210000",
        },
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Даниловский рынок"
    assert body["latitude"] == "55.7150000"
    assert body["is_active"] is True


def test_create_market_without_coordinates(committing_session):
    """Рынок заводится по названию и адресу — точку снимут позже."""
    client, headers = setup(committing_session, name="Админ рынков 2")

    response = client.post(
        "/api/v1/admin/markets",
        json={"name": "Рынок без точки", "address": "Москва, Тестовая, 3"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["latitude"] is None


def test_list_markets_includes_closed_ones(committing_session):
    client, headers = setup(committing_session, name="Админ рынков 3")
    created = client.post(
        "/api/v1/admin/markets",
        json={"name": "Рынок, который закроют", "address": "Москва, Тестовая, 4"},
        headers=headers,
    ).json()
    client.put(f"/api/v1/admin/markets/{created['id']}", json={"is_active": False}, headers=headers)

    response = client.get("/api/v1/admin/markets", headers=headers)

    app.dependency_overrides.clear()
    closed = next(m for m in response.json()["markets"] if m["id"] == created["id"])
    assert closed["is_active"] is False


def test_update_market_sets_coordinates(committing_session):
    client, headers = setup(committing_session, name="Админ рынков 4")
    created = client.post(
        "/api/v1/admin/markets",
        json={"name": "Рынок, которому снимут точку", "address": "Москва, Тестовая, 5"},
        headers=headers,
    ).json()

    response = client.put(
        f"/api/v1/admin/markets/{created['id']}",
        json={"latitude": "55.7000000", "longitude": "37.6000000"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert (response.json()["latitude"], response.json()["longitude"]) == ("55.7000000", "37.6000000")


def test_update_missing_market_reports_404(committing_session):
    client, headers = setup(committing_session, name="Админ рынков 5")

    response = client.put("/api/v1/admin/markets/999999", json={"name": "Нет такого"}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MARKET_NOT_FOUND"


def test_markets_require_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/markets")

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_rejects_out_of_range_coordinates(committing_session):
    """Широта вне [-90, 90] — опечатка, а не точка на Земле."""
    client, headers = setup(committing_session, name="Админ рынков 6")

    response = client.post(
        "/api/v1/admin/markets",
        json={"name": "Рынок на Луне", "address": "Море Спокойствия", "latitude": "95.0", "longitude": "0.0"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def test_get_groups_returns_seeded_groups(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера groups")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/groups")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    ids = [g["id"] for g in body["groups"]]
    assert group_id in ids
    matching = next(g for g in body["groups"] if g["id"] == group_id)
    assert matching["product_count"] == 0

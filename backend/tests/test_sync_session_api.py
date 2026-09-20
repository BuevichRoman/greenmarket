"""Sync Session API — то, ради чего сессия вообще живёт на сервере:
пережить перезагрузку страницы и не смешаться с сессией соседней вкладки."""

import uuid

from fastapi import Header
from sqlalchemy import text

from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.main import app
from app.sync.fingerprint import catalog_fingerprint

TOKEN = "sync-session-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "/api/v1/seller/catalog/sync-sessions"


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:n)"), {"n": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:u)"), {"u": user_id}).lastrowid


def add_offer(session, seller_id, *, name, price=100):
    return SellerProductRepository(session).create(
        seller_id=seller_id, product_id=None, seller_name=name, price=price, stock=1,
        unit="кг", description=None, is_published=False,
    )


def client_for(session, seller_id: int, user_id: int):
    from fastapi.testclient import TestClient

    from app.api.v1.seller import get_seller_bearer_access
    from app.infrastructure.database import get_session
    from app.publication.seller_access import SellerAccess

    def resolver(authorization: str | None = Header(default=None)):
        if authorization is None or authorization.lower() != f"bearer {TOKEN}":
            return None
        return SellerAccess(seller_id=seller_id, published_by=user_id, name="Продавец")

    app.dependency_overrides[get_session] = lambda: (yield session)
    app.dependency_overrides[get_seller_bearer_access] = resolver
    return TestClient(app)


def sheet_hash(session, seller_id: int) -> str:
    return catalog_fingerprint(SellerProductRepository(session).list_by_seller(seller_id))


def test_create_session_returns_active_without_baseline(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма создания сессии API")
    user_id = insert_user(committing_session, name="Пользователь создания сессии API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.post(BASE, json={}, headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["baseline_ready"] is False


def test_session_without_token_returns_401(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма сессии без токена")
    user_id = insert_user(committing_session, name="Пользователь сессии без токена")
    client = client_for(committing_session, seller_id, user_id)

    response = client.post(BASE, json={})

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_baseline_requires_matching_sheet_hash(committing_session):
    """Шлюз: пока клиент не доказал равенство книги и каталога, снимка нет."""
    seller_id = insert_seller(committing_session, name="Ферма шлюза API")
    user_id = insert_user(committing_session, name="Пользователь шлюза API")
    add_offer(committing_session, seller_id, name="Товар шлюза API")
    client = client_for(committing_session, seller_id, user_id)
    created = client.post(BASE, json={}, headers=AUTH).json()

    bad = client.post(
        f"{BASE}/{created['session_id']}/baseline", json={"sheet_catalog_hash": "чужой"}, headers=AUTH
    )
    state = client.get(f"{BASE}/{created['session_id']}", headers=AUTH).json()

    app.dependency_overrides.clear()
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "CATALOG_SHEET_MISMATCH"
    assert state["baseline_ready"] is False


def test_baseline_survives_reload(committing_session):
    """Главный смысл задачи: снимок лежит на сервере и достаётся обратно."""
    seller_id = insert_seller(committing_session, name="Ферма перезагрузки")
    user_id = insert_user(committing_session, name="Пользователь перезагрузки")
    offer = add_offer(committing_session, seller_id, name="Товар перезагрузки", price=250)
    client = client_for(committing_session, seller_id, user_id)
    created = client.post(BASE, json={}, headers=AUTH).json()
    client.post(
        f"{BASE}/{created['session_id']}/baseline",
        json={"sheet_catalog_hash": sheet_hash(committing_session, seller_id)}, headers=AUTH,
    )

    # «Перезагрузка»: клиент ничего не помнит и спрашивает сервер заново.
    state = client.get(f"{BASE}/{created['session_id']}", headers=AUTH).json()
    baseline = client.get(f"{BASE}/{created['session_id']}/baseline", headers=AUTH).json()

    app.dependency_overrides.clear()
    assert state["baseline_ready"] is True
    assert [i["seller_product_id"] for i in baseline["items"]] == [offer.id]
    assert baseline["items"][0]["price"] == "250.00"


def test_baseline_does_not_follow_catalog_changes(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма неизменности API")
    user_id = insert_user(committing_session, name="Пользователь неизменности API")
    offer = add_offer(committing_session, seller_id, name="Товар неизменности API", price=100)
    client = client_for(committing_session, seller_id, user_id)
    created = client.post(BASE, json={}, headers=AUTH).json()
    client.post(
        f"{BASE}/{created['session_id']}/baseline",
        json={"sheet_catalog_hash": sheet_hash(committing_session, seller_id)}, headers=AUTH,
    )

    client.patch(
        f"/api/v1/seller/products/{offer.id}", json={"price": "999.00", "expected_version": 1}, headers=AUTH
    )
    baseline = client.get(f"{BASE}/{created['session_id']}/baseline", headers=AUTH).json()
    state = client.get(f"{BASE}/{created['session_id']}", headers=AUTH).json()

    app.dependency_overrides.clear()
    assert baseline["items"][0]["price"] == "100.00"
    assert state["db_changed_since_baseline"] is True


def test_foreign_session_looks_like_missing(committing_session):
    mine = insert_seller(committing_session, name="Ферма своей сессии API")
    theirs = insert_seller(committing_session, name="Ферма чужой сессии API")
    user_id = insert_user(committing_session, name="Пользователь чужой сессии API")
    other_client = client_for(committing_session, theirs, user_id)
    foreign = other_client.post(BASE, json={}, headers=AUTH).json()
    app.dependency_overrides.clear()

    client = client_for(committing_session, mine, user_id)
    response = client.get(f"{BASE}/{foreign['session_id']}", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SYNC_SESSION_NOT_FOUND"


def test_repeated_session_creation_with_key_does_not_duplicate(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма повтора сессии API")
    user_id = insert_user(committing_session, name="Пользователь повтора сессии API")
    client = client_for(committing_session, seller_id, user_id)
    key = str(uuid.uuid4())

    first = client.post(BASE, json={"idempotency_key": key}, headers=AUTH).json()
    second = client.post(BASE, json={"idempotency_key": key}, headers=AUTH).json()

    app.dependency_overrides.clear()
    assert first["session_id"] == second["session_id"]


def test_repeated_baseline_request_returns_the_same_snapshot(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма повтора снимка API")
    user_id = insert_user(committing_session, name="Пользователь повтора снимка API")
    add_offer(committing_session, seller_id, name="Товар повтора снимка API")
    client = client_for(committing_session, seller_id, user_id)
    created = client.post(BASE, json={}, headers=AUTH).json()
    digest = sheet_hash(committing_session, seller_id)

    first = client.post(f"{BASE}/{created['session_id']}/baseline", json={"sheet_catalog_hash": digest}, headers=AUTH)
    second = client.post(f"{BASE}/{created['session_id']}/baseline", json={"sheet_catalog_hash": digest}, headers=AUTH)

    app.dependency_overrides.clear()
    assert first.json()["items"] == second.json()["items"]
    assert first.json()["created_at"] == second.json()["created_at"]


def test_invalidate_blocks_further_baseline(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма инвалидации API")
    user_id = insert_user(committing_session, name="Пользователь инвалидации API")
    add_offer(committing_session, seller_id, name="Товар инвалидации API")
    client = client_for(committing_session, seller_id, user_id)
    created = client.post(BASE, json={}, headers=AUTH).json()

    client.post(f"{BASE}/{created['session_id']}/invalidate", headers=AUTH)
    response = client.post(
        f"{BASE}/{created['session_id']}/baseline",
        json={"sheet_catalog_hash": sheet_hash(committing_session, seller_id)}, headers=AUTH,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYNC_SESSION_NOT_USABLE"

"""Seller Catalog API — чтение. Bearer, изоляция продавцов, справочники."""

import uuid

from fastapi import Header
from sqlalchemy import text

from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.main import app

TOKEN = "seller-admin-token"


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:u)"), {"u": user_id}).lastrowid


def insert_group(session, *, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name, is_active) VALUES (:n, :a)"),
        {"n": f"{name} {uuid.uuid4().hex[:6]}", "a": is_active},
    ).lastrowid


def insert_product(session, *, group_id: int, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name, is_active) VALUES (:g, :n, :a)"),
        {"g": group_id, "n": f"{name} {uuid.uuid4().hex[:6]}", "a": is_active},
    ).lastrowid


def add_offer(session, seller_id, *, name, product_id=None, price=100):
    return SellerProductRepository(session).create(
        seller_id=seller_id, product_id=product_id, seller_name=name,
        price=price, stock=1, unit="кг", description=None, is_published=False,
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


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_list_products_returns_own_catalog(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма списка API")
    user_id = insert_user(committing_session, name="Пользователь списка API")
    add_offer(committing_session, seller_id, name="Товар списка API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert [item["seller_name"] for item in body["items"]] == ["Товар списка API"]


def test_list_products_without_token_returns_401(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма без токена API")
    user_id = insert_user(committing_session, name="Пользователь без токена API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_list_products_rejects_unknown_sort_field(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма сортировки API")
    user_id = insert_user(committing_session, name="Пользователь сортировки API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products?sort=moderator_id", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_products_rejects_page_size_above_limit(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма размера страницы")
    user_id = insert_user(committing_session, name="Пользователь размера страницы")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products?page_size=101", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_detail_returns_own_product_with_photos_field(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма карточки API")
    user_id = insert_user(committing_session, name="Пользователь карточки API")
    offer = add_offer(committing_session, seller_id, name="Товар карточки API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get(f"/api/v1/seller/products/{offer.id}", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == offer.id
    assert body["photos"] == []
    assert body["product_name"] is None
    assert body["moderation_status"] == "WAIT_PRODUCT"


def test_detail_of_foreign_product_looks_like_missing(committing_session):
    """Чужая позиция неотличима от несуществующей — иначе перебором id можно
    выяснить состав чужого каталога."""
    mine = insert_seller(committing_session, name="Ферма своя карточка")
    theirs = insert_seller(committing_session, name="Ферма чужая карточка")
    user_id = insert_user(committing_session, name="Пользователь чужой карточки")
    foreign = add_offer(committing_session, theirs, name="Чужой товар карточки")
    client = client_for(committing_session, mine, user_id)

    response = client.get(f"/api/v1/seller/products/{foreign.id}", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_PRODUCT_NOT_FOUND"


def test_suggest_rejects_empty_query(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма пустого q")
    user_id = insert_user(committing_session, name="Пользователь пустого q")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products/suggest?q=%20%20", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_suggest_returns_active_products_with_their_group(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма подсказок")
    user_id = insert_user(committing_session, name="Пользователь подсказок")
    group_id = insert_group(committing_session, name="Группа подсказок")
    insert_product(committing_session, group_id=group_id, name="Черимойя подсказка")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products/suggest?q=Черимойя", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["product_group_id"] == group_id


def test_suggest_omits_inactive_product_and_inactive_group(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма скрытых подсказок")
    user_id = insert_user(committing_session, name="Пользователь скрытых подсказок")
    active_group = insert_group(committing_session, name="Активная группа подсказок")
    hidden_group = insert_group(committing_session, name="Скрытая группа подсказок", is_active=False)
    insert_product(committing_session, group_id=active_group, name="Дуриан скрытый", is_active=False)
    insert_product(committing_session, group_id=hidden_group, name="Дуриан в скрытой группе")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products/suggest?q=Дуриан", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.json()["items"] == []


def test_suggest_caps_limit_at_fifty(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма лимита подсказок")
    user_id = insert_user(committing_session, name="Пользователь лимита подсказок")
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/products/suggest?q=что-нибудь&limit=51", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_product_groups_omit_inactive(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма групп")
    user_id = insert_user(committing_session, name="Пользователь групп")
    hidden = insert_group(committing_session, name="Скрытая группа списка", is_active=False)
    client = client_for(committing_session, seller_id, user_id)

    response = client.get("/api/v1/seller/product-groups", headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert hidden not in [group["id"] for group in response.json()["items"]]

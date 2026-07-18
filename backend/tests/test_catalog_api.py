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


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid


def insert_active_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_seller_product(session, *, seller_id: int, product_id: int, price) -> int:
    return session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец роутера', :price, 'шт')"
        ),
        {"seller_id": seller_id, "product_id": product_id, "price": price},
    ).lastrowid


def test_get_products_returns_visible_product_with_min_price(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера products")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар для роутера products")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера products")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=42)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products?group_id={group_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    item = next(i for i in body["products"] if i["id"] == product_id)
    # price column is Numeric(12, 2), so the DB always returns 2 decimal places
    # (Decimal('42.00')), which Pydantic serializes as-is, not normalized to "42".
    assert item["min_price"] == "42.00"
    assert item["offer_count"] == 1
    assert body["page"] == 1
    assert body["limit"] == 20


def test_get_products_rejects_invalid_limit(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products?limit=0")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_product_by_id_returns_offers(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера product detail")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар для роутера detail")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера detail")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=15)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products/{product_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == product_id
    assert len(body["offers"]) == 1
    # SellerProduct.price is Numeric(12, 2) — Pydantic/JSON serializes Decimal
    # with its full scale, so this is "15.00", not "15" (same fixed-scale
    # behavior already hit and fixed in Task 8's router test).
    assert body["offers"][0]["price"] == "15.00"


def test_get_product_by_id_returns_404_for_missing_product(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products/999999")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

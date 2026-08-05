"""Admin API очереди модерации (Admin_MVP.md, экран 3).

Модерация Stage 1 — классификация: в очереди лежат предложения продавцов без
связи с Product, а работа модератора состоит в том, чтобы эту связь проставить.
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


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def admin_headers(session, client, *, name: str) -> tuple[dict[str, str], int]:
    """Возвращает заголовки и user_id администратора — moderator_id ссылается
    на пользователя платформы, а не на Administrator.id."""
    user_id = insert_user(session, name=name)
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid


def insert_product(session, *, name: str, is_active: bool = True) -> int:
    group_id = session.execute(
        text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": f"Группа {name}"}
    ).lastrowid
    return session.execute(
        text("INSERT INTO Product (product_group_id, name, is_active) VALUES (:group_id, :name, :is_active)"),
        {"group_id": group_id, "name": name, "is_active": is_active},
    ).lastrowid


def insert_offer(session, *, seller_id: int, name: str, product_id: int | None = None) -> int:
    """SellerProduct.seller_name — наименование товара, как его дал продавец
    (не имя продавца, см. Catalog_Model.md)."""
    return session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, is_published, "
            "moderation_status) VALUES (:seller_id, :product_id, :name, 99, 'кг', TRUE, :status)"
        ),
        {
            "seller_id": seller_id,
            "product_id": product_id,
            "name": name,
            "status": "WAIT_PRODUCT" if product_id is None else "RESOLVED",
        },
    ).lastrowid


def attach_photo(session, *, seller_product_id: int, s3_key: str) -> None:
    photo_id = session.execute(
        text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}
    ).lastrowid
    session.execute(
        text(
            "INSERT INTO SellerProductPhoto (seller_product_id, photo_id, sort_order) "
            "VALUES (:seller_product_id, :photo_id, 0)"
        ),
        {"seller_product_id": seller_product_id, "photo_id": photo_id},
    )


def test_queue_contains_only_unclassified_offers(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ очереди")
    seller_id = insert_seller(committing_session, name="Ферма очереди")
    product_id = insert_product(committing_session, name="Яблоко эталонное")
    waiting = insert_offer(committing_session, seller_id=seller_id, name="Яблочки свои")
    classified = insert_offer(
        committing_session, seller_id=seller_id, name="Груши свои", product_id=product_id
    )
    attach_photo(committing_session, seller_product_id=waiting, s3_key="moderation/apple.jpg")

    response = client.get("/api/v1/admin/moderation", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    ids = [item["seller_product_id"] for item in body["items"]]
    assert waiting in ids
    assert classified not in ids
    item = next(i for i in body["items"] if i["seller_product_id"] == waiting)
    assert item["name"] == "Яблочки свои"
    assert item["seller_id"] == seller_id
    # seller_name — имя продавца, как в Catalog API; наименование товара лежит в name
    assert item["seller_name"] == "Ферма очереди"
    assert item["unit"] == "кг"
    assert item["moderation_status"] == "WAIT_PRODUCT"
    # Фото — то, по чему модератор вообще понимает, что за товар ему принесли
    assert len(item["photos"]) == 1


def test_queue_paginates(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ страниц")
    seller_id = insert_seller(committing_session, name="Ферма страниц")
    for index in range(3):
        insert_offer(committing_session, seller_id=seller_id, name=f"Позиция {index}")

    response = client.get("/api/v1/admin/moderation?page=1&limit=2", headers=headers)

    app.dependency_overrides.clear()
    body = response.json()
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total"] >= 3


def test_queue_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/moderation")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_resolve_links_offer_and_makes_it_visible_to_buyers(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, admin_user_id = admin_headers(committing_session, client, name="Админ модерации")
    seller_id = insert_seller(committing_session, name="Ферма модерации")
    product_id = insert_product(committing_session, name="Яблоко модерации")
    offer_id = insert_offer(committing_session, seller_id=seller_id, name="Яблочки без справочника")

    # До модерации предложение не привязано ни к чему: у позиции справочника
    # нет ни одного видимого предложения, поэтому покупателю её вообще нет.
    assert client.get(f"/api/v1/catalog/products/{product_id}").status_code == 404

    response = client.put(
        f"/api/v1/admin/moderation/{offer_id}",
        json={"product_id": product_id, "comment": "Обычные яблоки"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == product_id
    assert body["moderation_status"] == "RESOLVED"
    assert body["moderator_id"] == admin_user_id
    assert body["moderated_at"] is not None
    assert body["moderation_comment"] == "Обычные яблоки"

    # Позиция ушла из очереди и появилась у покупателя — в этом и смысл операции.
    queue_ids = [i["seller_product_id"] for i in client.get("/api/v1/admin/moderation", headers=headers).json()["items"]]
    assert offer_id not in queue_ids
    after = client.get(f"/api/v1/catalog/products/{product_id}").json()
    assert [offer["seller_product_id"] for offer in after["offers"]] == [offer_id]
    app.dependency_overrides.clear()


def test_resolve_rejects_unknown_offer(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ неизвестной позиции")
    product_id = insert_product(committing_session, name="Товар для неизвестной позиции")

    response = client.put(
        "/api/v1/admin/moderation/999999", json={"product_id": product_id}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_PRODUCT_NOT_FOUND"


def test_resolve_rejects_unknown_product(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ неизвестного товара очереди")
    seller_id = insert_seller(committing_session, name="Ферма неизвестного товара")
    offer_id = insert_offer(committing_session, seller_id=seller_id, name="Позиция без товара")

    response = client.put(
        f"/api/v1/admin/moderation/{offer_id}", json={"product_id": 999999}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_resolve_rejects_inactive_product(committing_session):
    """Привязка к выключенной позиции справочника выглядит как завершённая
    модерация, но покупателю товар всё равно не показывается."""
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ выключенного товара")
    seller_id = insert_seller(committing_session, name="Ферма выключенного товара")
    product_id = insert_product(committing_session, name="Выключенная позиция", is_active=False)
    offer_id = insert_offer(committing_session, seller_id=seller_id, name="Позиция в выключенный товар")

    response = client.put(
        f"/api/v1/admin/moderation/{offer_id}", json={"product_id": product_id}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INACTIVE_PRODUCT"
    assert committing_session.execute(
        text("SELECT product_id FROM SellerProduct WHERE id = :id"), {"id": offer_id}
    ).scalar() is None


def test_resolve_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    seller_id = insert_seller(committing_session, name="Ферма без токена")
    product_id = insert_product(committing_session, name="Товар без токена")
    offer_id = insert_offer(committing_session, seller_id=seller_id, name="Позиция без токена")

    response = client.put(f"/api/v1/admin/moderation/{offer_id}", json={"product_id": product_id})

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert committing_session.execute(
        text("SELECT product_id FROM SellerProduct WHERE id = :id"), {"id": offer_id}
    ).scalar() is None

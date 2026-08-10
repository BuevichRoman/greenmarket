from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app
from app.profile.fields import PROFILE_FIELDS
from app.profile.seller_profile_service import SellerProfileService


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
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, is_published) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец роутера', :price, 'шт', TRUE)"
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


def test_get_product_by_id_returns_product_group(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера карточки")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар с группой в роутере")
    seller_id = insert_active_seller(committing_session, name="Продавец для группы в роутере")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=15)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products/{product_id}")

    app.dependency_overrides.clear()
    body = response.json()
    assert body["group_id"] == group_id
    assert body["group_name"] == "Группа для роутера карточки"


def test_get_product_by_id_returns_404_for_missing_product(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products/999999")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def insert_seller_with_user(session, *, name: str, is_active: bool = True, phone: int | None = None) -> tuple[int, int]:
    """Возвращает (seller_id, user_id). Отличается от insert_active_seller тем,
    что отдаёт user_id (нужен как автор изменений профиля) и умеет создавать
    неактивного продавца и заполнять учётный телефон платформы."""
    user_id = session.execute(
        text("INSERT INTO users (name, phone) VALUES (:name, :phone)"), {"name": name, "phone": phone}
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id, is_active) VALUES (:user_id, :is_active)"),
        {"user_id": user_id, "is_active": is_active},
    ).lastrowid
    return seller_id, user_id


def test_seller_card_returns_profile_fields(committing_session):
    seller_id, user_id = insert_seller_with_user(committing_session, name="Пасека Ромашково")
    SellerProfileService(committing_session).apply(
        seller_id,
        {"row": "Ряд 3", "place": "Место 12", "phone": "+79990000000", "working_hours": "8:00–18:00"},
        author_user_id=user_id,
        author_role="SELLER",
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["name"] == "Пасека Ромашково"
    assert body["row"] == "Ряд 3"
    assert body["place"] == "Место 12"
    assert body["phone"] == "+79990000000"
    assert body["working_hours"] == "8:00–18:00"
    assert body["short_description"] is None
    # Состав ответа выводится из fields.py — единственного источника правды о
    # профиле: седьмое поле, добавленное в Stage 2, должно уронить этот тест, а
    # не тихо не доехать до HTTP-контракта (SellerCardResponse(**card) лишние
    # ключи молча отбросит).
    #
    # Равенство держится ровно потому, что все поля Stage 1 публичны
    # (Seller_Profile.md, §7). Появление непубличного поля — повод осознанно
    # переписать этот ассерт под фильтр в get_seller_card, а не дописать поле
    # в карточку, чтобы тест позеленел.
    assert set(body) == {"seller_id", "name"} | {field.name for field in PROFILE_FIELDS}


def test_seller_card_hides_inactive_seller(committing_session):
    seller_id, _ = insert_seller_with_user(committing_session, name="Скрытый продавец", is_active=False)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_seller_card_404_for_missing_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/sellers/999999")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_seller_card_never_exposes_platform_phone(committing_session):
    """Учётный телефон платформы — не витринный контакт: пока продавец не
    сохранил свой, покупателю показывать нечего."""
    seller_id, _ = insert_seller_with_user(
        committing_session, name="Без телефона в профиле", phone=79990000000
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.json()["phone"] is None
    # suggested_phone — подсказка для формы продавца, а не витринный контакт:
    # в карточке покупателя такого ключа нет вообще.
    assert "suggested_phone" not in response.json()


def test_seller_card_name_comes_from_users_not_from_offer(committing_session):
    """`SellerProduct.seller_name` — это НАЗВАНИЕ ТОВАРА продавца, а имя самого
    продавца живёт в платформенной `users.name` (Seller_Profile.md, §5).
    Названия обманчиво похожи, и путаница между ними уже была источником бага."""
    seller_id, _ = insert_seller_with_user(committing_session, name="Пасека Ромашково")
    group_id = insert_product_group(committing_session, name="Группа для карточки продавца")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар для карточки продавца")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=10)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.json()["name"] == "Пасека Ромашково"


def test_seller_card_is_public(committing_session):
    """Витрина: ни токена, ни заголовков. Тест зафиксирован явно, чтобы
    аутентификацию сюда не «починили»."""
    seller_id, _ = insert_seller_with_user(committing_session, name="Публичный продавец")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/catalog/sellers/{seller_id}"]["get"]

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "security" not in operation
    assert [parameter["name"] for parameter in operation.get("parameters", [])] == ["seller_id"]

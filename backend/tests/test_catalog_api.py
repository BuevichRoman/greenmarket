from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app
from app.profile.fields import PROFILE_FIELDS
from app.profile.seller_profile_service import SellerProfileService


def insert_product_group(session, *, name: str, parent_id: int | None = None) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name, parent_id) VALUES (:name, :parent_id)"),
        {"name": name, "parent_id": parent_id},
    ).lastrowid


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


def test_get_product_by_id_returns_origin_country_and_supply_date(committing_session):
    group_id = insert_product_group(committing_session, name="Группа страны в роутере")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар страны в роутере")
    seller_id = insert_active_seller(committing_session, name="Продавец страны в роутере")
    offer_id = insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=15)
    committing_session.execute(
        text("UPDATE SellerProduct SET origin_country = 'Египет', supply_date = '2026-08-05' WHERE id = :id"),
        {"id": offer_id},
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products/{product_id}")

    app.dependency_overrides.clear()
    offer = response.json()["offers"][0]
    assert offer["origin_country"] == "Египет"
    assert offer["supply_date"] == "2026-08-05"


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
    #
    # `market_id` — как раз такой случай (10.08.2026): идентификатор рынка
    # покупателю бесполезен, ему нужны название, адрес и координаты, поэтому
    # карточка отдаёт вместо него объект `market`.
    profile_keys = {field.name for field in PROFILE_FIELDS} - {"market_id"}
    assert set(body) == {"seller_id", "name", "market"} | profile_keys


def test_seller_card_returns_market_with_coordinates(committing_session):
    seller_id, user_id = insert_seller_with_user(committing_session, name="Продавец с рынком")
    market_id = committing_session.execute(
        text(
            "INSERT INTO Market (name, address, latitude, longitude, is_active) "
            "VALUES ('Даниловский рынок', 'Москва, Мытная, 74', 55.7150000, 37.6210000, TRUE)"
        )
    ).lastrowid
    SellerProfileService(committing_session).apply(
        seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER"
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    market = response.json()["market"]
    assert market["id"] == market_id
    assert market["name"] == "Даниловский рынок"
    assert market["type"] == "MARKET"
    assert market["address"] == "Москва, Мытная, 74"
    assert (market["latitude"], market["longitude"]) == ("55.7150000", "37.6210000")


def test_seller_card_returns_shop_type(committing_session):
    """Лавка — отдельно стоящая точка (Валентин, 10.08): на карте её пин это
    сам продавец, а не сотня продавцов одного рынка."""
    seller_id, user_id = insert_seller_with_user(committing_session, name="Продавец с лавкой")
    market_id = committing_session.execute(
        text(
            "INSERT INTO Market (name, type, address, is_active) "
            "VALUES ('Лавка у дома', 'SHOP', 'Казань, Баумана, 5', TRUE)"
        )
    ).lastrowid
    SellerProfileService(committing_session).apply(
        seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER"
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.json()["market"]["type"] == "SHOP"


def test_seller_card_without_market_returns_null(committing_session):
    """Продавец, не выбравший рынок, — штатное состояние, а не ошибка."""
    seller_id, _ = insert_seller_with_user(committing_session, name="Продавец без рынка")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.json()["market"] is None


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


def _publish(session, *, group_id: int, product_name: str, seller_name: str) -> int:
    product_id = insert_product(session, group_id=group_id, name=product_name)
    seller_id = insert_active_seller(session, name=seller_name)
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)
    return product_id


def test_get_products_accepts_comma_separated_group_ids(committing_session):
    group_a = insert_product_group(committing_session, name="Группа A запятой")
    group_b = insert_product_group(committing_session, name="Группа B запятой")
    group_c = insert_product_group(committing_session, name="Группа C запятой")
    product_a = _publish(committing_session, group_id=group_a, product_name="Товар A запятой", seller_name="Продавец A запятой")
    product_b = _publish(committing_session, group_id=group_b, product_name="Товар B запятой", seller_name="Продавец B запятой")
    product_c = _publish(committing_session, group_id=group_c, product_name="Товар C запятой", seller_name="Продавец C запятой")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products?group_id={group_a},{group_b}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    ids = [i["id"] for i in response.json()["products"]]
    assert product_a in ids
    assert product_b in ids
    assert product_c not in ids


def test_get_products_accepts_repeated_group_id_parameter(committing_session):
    """`group_id=12&group_id=17` — второй способ перечисления, который умеет
    любой HTTP-клиент по умолчанию. Оба формата означают одно и то же."""
    group_a = insert_product_group(committing_session, name="Группа A повтора")
    group_b = insert_product_group(committing_session, name="Группа B повтора")
    product_a = _publish(committing_session, group_id=group_a, product_name="Товар A повтора", seller_name="Продавец A повтора")
    product_b = _publish(committing_session, group_id=group_b, product_name="Товар B повтора", seller_name="Продавец B повтора")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products?group_id={group_a}&group_id={group_b}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    ids = [i["id"] for i in response.json()["products"]]
    assert product_a in ids
    assert product_b in ids


def test_get_products_by_parent_group_returns_child_products(committing_session):
    parent = insert_product_group(committing_session, name="Родитель роутера ветки")
    child = insert_product_group(committing_session, name="Ребёнок роутера ветки", parent_id=parent)
    child_product = _publish(
        committing_session, group_id=child, product_name="Товар ребёнка роутера", seller_name="Продавец ветки роутера"
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products?group_id={parent}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert child_product in [i["id"] for i in response.json()["products"]]


def test_get_products_rejects_non_numeric_group_id(committing_session):
    """Мусор в `group_id` — ошибка, а не «фильтра нет»: молча отданный каталог
    целиком выглядит на фронте как применившийся фильтр."""
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products?group_id=12,abc")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_products_treats_empty_group_id_as_no_filter(committing_session):
    """Сброс фильтра интерфейс присылает пустым значением — это не ошибка."""
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products?group_id=")

    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_get_suggest_returns_flat_names(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера suggest")
    product_id = insert_product(committing_session, group_id=group_id, name="Клюква вяленая для роутера suggest")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера suggest")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=42)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/suggest?q=клюква&group_id={group_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"suggestions": ["Клюква вяленая для роутера suggest"]}


def test_get_suggest_rejects_non_numeric_group_id(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/suggest?group_id=овощи")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_suggest_returns_at_most_ten_names_by_default(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера suggest limit")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера suggest limit")
    for index in range(12):
        product_id = insert_product(
            committing_session, group_id=group_id, name=f"Товар {index:02d} для роутера suggest limit"
        )
        insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=10)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/suggest?group_id={group_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["suggestions"]) == 10

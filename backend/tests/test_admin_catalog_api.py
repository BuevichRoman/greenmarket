"""Admin API справочника: ProductGroup и Product (Admin_MVP.md, экраны 1 и 2).

Справочник — то, чем модератор закрывает очередь: позиция продавца либо
привязывается к существующему Product, либо требует завести новый.
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


def admin_headers(session, client, *, name: str) -> dict[str, str]:
    user_id = insert_user(session, name=name)
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_group(client, headers, *, name: str, parent_id: int | None = None) -> dict:
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return client.post("/api/v1/admin/product-groups", json=body, headers=headers).json()


# --- ProductGroup ---------------------------------------------------------


def test_create_group_returns_created_group(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ групп")

    response = client.post("/api/v1/admin/product-groups", json={"name": "Ягоды"}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Ягоды"
    assert body["parent_id"] is None
    assert body["is_active"] is True
    assert body["product_count"] == 0


def test_create_group_under_parent(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ подгрупп")
    parent = create_group(client, headers, name="Ягоды садовые")

    response = client.post(
        "/api/v1/admin/product-groups", json={"name": "Клубника", "parent_id": parent["id"]}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["parent_id"] == parent["id"]


def test_create_group_rejects_unknown_parent(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ несуществующего родителя")

    response = client.post(
        "/api/v1/admin/product-groups", json={"name": "Сирота", "parent_id": 999999}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_GROUP_NOT_FOUND"


def test_list_groups_shows_deactivated_and_counts_products(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ списка групп")
    group = create_group(client, headers, name="Группа со счётчиком")
    client.post(
        "/api/v1/admin/products",
        json={"product_group_id": group["id"], "name": "Товар в группе"},
        headers=headers,
    )
    hidden = create_group(client, headers, name="Группа выключенная")
    client.put(f"/api/v1/admin/product-groups/{hidden['id']}", json={"is_active": False}, headers=headers)

    response = client.get("/api/v1/admin/product-groups", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    groups = {g["id"]: g for g in response.json()["groups"]}
    assert groups[group["id"]]["product_count"] == 1
    # Деактивированная группа не исчезает из админки — иначе её нельзя вернуть.
    assert groups[hidden["id"]]["is_active"] is False


def test_update_group_renames_moves_and_deactivates(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ правки групп")
    parent = create_group(client, headers, name="Новый родитель")
    group = create_group(client, headers, name="Старое имя")

    response = client.put(
        f"/api/v1/admin/product-groups/{group['id']}",
        json={"name": "Новое имя", "parent_id": parent["id"], "is_active": False, "sort_order": 5},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Новое имя"
    assert body["parent_id"] == parent["id"]
    assert body["is_active"] is False
    assert body["sort_order"] == 5


def test_update_group_rejects_itself_as_parent(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ самородителя")
    group = create_group(client, headers, name="Сам себе родитель")

    response = client.put(
        f"/api/v1/admin/product-groups/{group['id']}", json={"parent_id": group["id"]}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARENT_GROUP"


def test_update_group_rejects_own_descendant_as_parent(committing_session):
    """Перенос группы под собственного потомка отрывает ветку от дерева —
    в списке она останется, но ни в одну корневую ветку не попадёт."""
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ цикла")
    root = create_group(client, headers, name="Корень цикла")
    child = create_group(client, headers, name="Потомок цикла", parent_id=root["id"])

    response = client.put(
        f"/api/v1/admin/product-groups/{root['id']}", json={"parent_id": child["id"]}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARENT_GROUP"


def test_update_unknown_group_returns_404(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестной группы")

    response = client.put("/api/v1/admin/product-groups/999999", json={"name": "Нет такой"}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_GROUP_NOT_FOUND"


def test_group_endpoints_require_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    listed = client.get("/api/v1/admin/product-groups")
    created = client.post("/api/v1/admin/product-groups", json={"name": "Без токена"})

    app.dependency_overrides.clear()
    assert listed.status_code == 401
    assert created.status_code == 401
    assert committing_session.execute(
        text("SELECT COUNT(*) FROM ProductGroup WHERE name = 'Без токена'")
    ).scalar() == 0


# --- Product --------------------------------------------------------------


def test_create_product_returns_created_product(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ товаров")
    group = create_group(client, headers, name="Группа для товара")

    response = client.post(
        "/api/v1/admin/products",
        json={"product_group_id": group["id"], "name": "Клубника садовая", "description": "Эталонная позиция"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Клубника садовая"
    assert body["product_group_id"] == group["id"]
    assert body["group_name"] == "Группа для товара"
    assert body["description"] == "Эталонная позиция"
    assert body["is_active"] is True
    assert body["offer_count"] == 0


def test_create_product_rejects_unknown_group(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ товара без группы")

    response = client.post(
        "/api/v1/admin/products", json={"product_group_id": 999999, "name": "Ничей товар"}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_GROUP_NOT_FOUND"


def test_list_products_filters_by_group_and_query(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ поиска товаров")
    group = create_group(client, headers, name="Группа поиска")
    other = create_group(client, headers, name="Другая группа поиска")
    wanted = client.post(
        "/api/v1/admin/products", json={"product_group_id": group["id"], "name": "Яблоко Антоновка"}, headers=headers
    ).json()
    client.post(
        "/api/v1/admin/products", json={"product_group_id": group["id"], "name": "Груша Конференция"}, headers=headers
    )
    client.post(
        "/api/v1/admin/products", json={"product_group_id": other["id"], "name": "Яблоко Гренни"}, headers=headers
    )

    response = client.get(f"/api/v1/admin/products?group_id={group['id']}&query=яблок", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert [p["id"] for p in body["products"]] == [wanted["id"]]
    assert body["total"] == 1


def test_list_products_shows_deactivated_with_offer_count(committing_session):
    """Админ должен видеть выключенные позиции и число связанных предложений —
    Admin_MVP.md запрещает удалять Product при связанных SellerProduct."""
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ выключенных товаров")
    group = create_group(client, headers, name="Группа выключенных")
    product = client.post(
        "/api/v1/admin/products", json={"product_group_id": group["id"], "name": "Выключенный товар"}, headers=headers
    ).json()
    client.put(f"/api/v1/admin/products/{product['id']}", json={"is_active": False}, headers=headers)
    seller_user = insert_user(committing_session, name="Продавец предложения")
    seller_id = committing_session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": seller_user}
    ).lastrowid
    committing_session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit) "
            "VALUES (:seller_id, :product_id, 'Предложение', 10, 'шт')"
        ),
        {"seller_id": seller_id, "product_id": product["id"]},
    )

    response = client.get(f"/api/v1/admin/products?group_id={group['id']}", headers=headers)

    app.dependency_overrides.clear()
    item = next(p for p in response.json()["products"] if p["id"] == product["id"])
    assert item["is_active"] is False
    assert item["offer_count"] == 1


def test_update_product_moves_renames_and_deactivates(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ правки товара")
    group = create_group(client, headers, name="Исходная группа товара")
    target = create_group(client, headers, name="Целевая группа товара")
    product = client.post(
        "/api/v1/admin/products", json={"product_group_id": group["id"], "name": "Исходное имя"}, headers=headers
    ).json()

    response = client.put(
        f"/api/v1/admin/products/{product['id']}",
        json={"name": "Целевое имя", "product_group_id": target["id"], "is_active": False},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Целевое имя"
    assert body["product_group_id"] == target["id"]
    assert body["group_name"] == "Целевая группа товара"
    assert body["is_active"] is False


def test_update_product_rejects_unknown_group(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ переноса в никуда")
    group = create_group(client, headers, name="Группа переноса")
    product = client.post(
        "/api/v1/admin/products", json={"product_group_id": group["id"], "name": "Товар переноса"}, headers=headers
    ).json()

    response = client.put(
        f"/api/v1/admin/products/{product['id']}", json={"product_group_id": 999999}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_GROUP_NOT_FOUND"


def test_update_unknown_product_returns_404(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестного товара")

    response = client.put("/api/v1/admin/products/999999", json={"name": "Нет такого"}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_product_endpoints_require_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    listed = client.get("/api/v1/admin/products")
    created = client.post("/api/v1/admin/products", json={"product_group_id": 1, "name": "Без токена"})

    app.dependency_overrides.clear()
    assert listed.status_code == 401
    assert created.status_code == 401
    assert committing_session.execute(
        text("SELECT COUNT(*) FROM Product WHERE name = 'Без токена'")
    ).scalar() == 0

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


def test_create_seller_returns_seller_id_and_activation_code(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ онбординга")
    user_id = insert_user(committing_session, name="Фермер через API")

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] > 0
    assert body["activation_code"]


def test_create_seller_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    user_id = insert_user(committing_session, name="Фермер без админа")

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id})

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"
    assert committing_session.execute(
        text("SELECT COUNT(*) FROM Seller WHERE user_id = :id"), {"id": user_id}
    ).scalar() == 0


def test_create_seller_rejects_unknown_platform_user(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестного юзера")

    response = client.post("/api/v1/admin/sellers", json={"user_id": 999_999_999}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_create_seller_rejects_duplicate(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ дубля")
    user_id = insert_user(committing_session, name="Фермер дубль")
    first = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    response = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELLER_ALREADY_EXISTS"
    # seller_id существующего продавца должен быть в сообщении — иначе админу
    # некуда идти за перевыпуском кода.
    assert str(first.json()["seller_id"]) in response.json()["error"]["message"]


def test_reissue_activation_code_replaces_previous_one(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ перевыпуска")
    user_id = insert_user(committing_session, name="Фермер перевыпуск")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.post(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["activation_code"] != created["activation_code"]


def test_reissue_activation_code_rejects_unknown_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ несуществующего продавца")

    response = client.post("/api/v1/admin/sellers/999999/activation-code", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_revoke_activation_code_makes_it_unusable(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ отзыва")
    user_id = insert_user(committing_session, name="Фермер отзыв")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.delete(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code", headers=headers)

    assert response.status_code == 204
    activation = client.post(
        "/api/v1/seller/activate",
        json={"activation_code": created["activation_code"], "spreadsheet_id": "sheet-revoked"},
    )
    app.dependency_overrides.clear()
    assert activation.status_code == 400


def insert_offer(session, *, seller_id: int, price) -> int:
    """Опубликованное предложение продавца — чтобы проверять видимость каталога
    покупателем, а не только флаг в таблице."""
    group_id = session.execute(
        text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": f"Группа продавца {seller_id}"}
    ).lastrowid
    product_id = session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": f"Товар продавца {seller_id}"},
    ).lastrowid
    session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, is_published) "
            "VALUES (:seller_id, :product_id, 'Товар для проверки видимости', :price, 'шт', TRUE)"
        ),
        {"seller_id": seller_id, "product_id": product_id, "price": price},
    )
    return product_id


def test_list_sellers_returns_basic_information(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ списка")
    user_id = insert_user(committing_session, name="Фермер в списке")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.get("/api/v1/admin/sellers", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    seller = next(s for s in response.json()["sellers"] if s["seller_id"] == created["seller_id"])
    assert seller["user_id"] == user_id
    assert seller["name"] == "Фермер в списке"
    assert seller["is_active"] is True
    assert seller["current_catalog_version"] == 0
    # Продавец только подключён: код выдан, но на токен ещё не обменян —
    # администратор должен видеть эту разницу, иначе непонятно, ждём мы
    # продавца или он уже работает.
    assert seller["activated_at"] is None
    assert seller["activation_code_expires_at"] is not None


def test_list_sellers_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/sellers")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_deactivate_hides_catalog_and_activate_restores_it(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ деактивации")
    user_id = insert_user(committing_session, name="Фермер деактивации")
    seller_id = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()["seller_id"]
    product_id = insert_offer(committing_session, seller_id=seller_id, price=100)

    def catalog_shows_product() -> bool:
        body = client.get(f"/api/v1/catalog/products/{product_id}").json()
        return body.get("offers") not in (None, [])

    assert catalog_shows_product()

    deactivated = client.put(f"/api/v1/admin/sellers/{seller_id}/deactivate", headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert not catalog_shows_product()

    # Повторная активация возвращает последнюю опубликованную версию без
    # повторной публикации (Admin_MVP.md, «Временная деактивация»).
    activated = client.put(f"/api/v1/admin/sellers/{seller_id}/activate", headers=headers)

    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    assert catalog_shows_product()
    app.dependency_overrides.clear()


def test_deactivated_seller_keeps_working_in_cabinet(committing_session):
    """Деактивация — про видимость покупателю, а не про отключение продавца:
    кабинет и публикация ему остаются (решение коллеги от 2026-08-05)."""
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ деактивации кабинета")
    user_id = insert_user(committing_session, name="Фермер деактивации кабинета")
    seller_id = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()["seller_id"]
    committing_session.execute(
        text("UPDATE Seller SET access_token = :token WHERE id = :id"),
        {"token": "token-deactivated-seller", "id": seller_id},
    )
    client.put(f"/api/v1/admin/sellers/{seller_id}/deactivate", headers=headers)

    response = client.get("/api/v1/seller/catalog", params={"access_token": "token-deactivated-seller"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["is_active"] is False


def test_activate_is_idempotent(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ идемпотентности")
    user_id = insert_user(committing_session, name="Фермер идемпотентности")
    seller_id = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()["seller_id"]

    first = client.put(f"/api/v1/admin/sellers/{seller_id}/activate", headers=headers)
    second = client.put(f"/api/v1/admin/sellers/{seller_id}/activate", headers=headers)

    app.dependency_overrides.clear()
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_active"] is True


def test_activate_rejects_unknown_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестного продавца")

    response = client.put("/api/v1/admin/sellers/999999/activate", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_deactivate_rejects_unknown_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ неизвестного продавца 2")

    response = client.put("/api/v1/admin/sellers/999999/deactivate", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_deactivate_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ деактивации без токена")
    user_id = insert_user(committing_session, name="Фермер деактивации без токена")
    seller_id = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()["seller_id"]

    response = client.put(f"/api/v1/admin/sellers/{seller_id}/deactivate")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert committing_session.execute(
        text("SELECT is_active FROM Seller WHERE id = :id"), {"id": seller_id}
    ).scalar() == 1


def test_revoke_activation_code_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers = admin_headers(committing_session, client, name="Админ отзыва без токена")
    user_id = insert_user(committing_session, name="Фермер отзыв без токена")
    created = client.post("/api/v1/admin/sellers", json={"user_id": user_id}, headers=headers).json()

    response = client.delete(f"/api/v1/admin/sellers/{created['seller_id']}/activation-code")

    app.dependency_overrides.clear()
    assert response.status_code == 401

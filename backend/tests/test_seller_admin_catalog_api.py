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


# ── Запись ───────────────────────────────────────────────────────────────────

NEW_PRODUCT = {"seller_name": "Новый товар", "price": "250.00", "stock": "12.500", "unit": "кг"}


def test_create_product_returns_201_and_stays_hidden(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма создания API")
    user_id = insert_user(committing_session, name="Пользователь создания API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.post("/api/v1/seller/products", json=NEW_PRODUCT, headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["is_published"] is False
    assert body["moderation_status"] == "WAIT_PRODUCT"
    assert body["photos"] == []


def test_create_product_rejects_fields_the_seller_must_not_set(committing_session):
    """ТЗ перечисляет поля, которые от клиента не принимаются. Они просто не
    описаны в схеме, а лишние ключи запрещены — попытка даёт 422."""
    seller_id = insert_seller(committing_session, name="Ферма запрещённых полей")
    user_id = insert_user(committing_session, name="Пользователь запрещённых полей")
    client = client_for(committing_session, seller_id, user_id)

    response = client.post(
        "/api/v1/seller/products", json={**NEW_PRODUCT, "is_published": True}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_create_product_rejects_negative_price(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма отрицательной цены")
    user_id = insert_user(committing_session, name="Пользователь отрицательной цены")
    client = client_for(committing_session, seller_id, user_id)

    response = client.post(
        "/api/v1/seller/products", json={**NEW_PRODUCT, "price": "-1"}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_create_product_rejects_inactive_product_id(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма снятой позиции API")
    user_id = insert_user(committing_session, name="Пользователь снятой позиции API")
    group_id = insert_group(committing_session, name="Группа снятой позиции API")
    inactive = insert_product(committing_session, group_id=group_id, name="Снятая позиция API", is_active=False)
    client = client_for(committing_session, seller_id, user_id)

    response = client.post(
        "/api/v1/seller/products", json={**NEW_PRODUCT, "product_id": inactive}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_patch_product_saves_only_given_field(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма правки API")
    user_id = insert_user(committing_session, name="Пользователь правки API")
    offer = add_offer(committing_session, seller_id, name="Товар правки API", price=100)
    client = client_for(committing_session, seller_id, user_id)

    response = client.patch(
        f"/api/v1/seller/products/{offer.id}", json={"price": "777.00"}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "777.00"
    assert body["seller_name"] == "Товар правки API"


def test_patch_selecting_product_resolves_moderation(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма выбора позиции API")
    user_id = insert_user(committing_session, name="Пользователь выбора позиции API")
    group_id = insert_group(committing_session, name="Группа выбора позиции API")
    product_id = insert_product(committing_session, group_id=group_id, name="Позиция выбора API")
    offer = add_offer(committing_session, seller_id, name="Товар выбора позиции API")
    client = client_for(committing_session, seller_id, user_id)

    response = client.patch(
        f"/api/v1/seller/products/{offer.id}", json={"product_id": product_id}, headers=AUTH
    )

    app.dependency_overrides.clear()
    body = response.json()
    assert body["moderation_status"] == "RESOLVED"
    assert body["product_group_id"] == group_id


def test_patch_cannot_clear_seller_name(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма очистки имени")
    user_id = insert_user(committing_session, name="Пользователь очистки имени")
    offer = add_offer(committing_session, seller_id, name="Товар очистки имени")
    client = client_for(committing_session, seller_id, user_id)

    response = client.patch(
        f"/api/v1/seller/products/{offer.id}", json={"seller_name": None}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_patch_cannot_publish_product(committing_session):
    """Витрина меняется публикацией, а не сохранением карточки."""
    seller_id = insert_seller(committing_session, name="Ферма самопубликации")
    user_id = insert_user(committing_session, name="Пользователь самопубликации")
    offer = add_offer(committing_session, seller_id, name="Товар самопубликации")
    client = client_for(committing_session, seller_id, user_id)

    response = client.patch(
        f"/api/v1/seller/products/{offer.id}", json={"is_published": True}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_patch_foreign_product_is_not_found(committing_session):
    mine = insert_seller(committing_session, name="Ферма своя правка API")
    theirs = insert_seller(committing_session, name="Ферма чужая правка API")
    user_id = insert_user(committing_session, name="Пользователь чужой правки API")
    foreign = add_offer(committing_session, theirs, name="Чужой товар правки API")
    client = client_for(committing_session, mine, user_id)

    response = client.patch(f"/api/v1/seller/products/{foreign.id}", json={"price": "1"}, headers=AUTH)

    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_patch_duplicate_sku_returns_409(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма дубля артикула API")
    user_id = insert_user(committing_session, name="Пользователь дубля артикула API")
    taken = f"SKU-{uuid.uuid4().hex[:8]}"
    client = client_for(committing_session, seller_id, user_id)
    client.post("/api/v1/seller/products", json={**NEW_PRODUCT, "seller_sku": taken}, headers=AUTH)
    other = client.post(
        "/api/v1/seller/products", json={**NEW_PRODUCT, "seller_sku": f"SKU-{uuid.uuid4().hex[:8]}"}, headers=AUTH
    ).json()

    response = client.patch(
        f"/api/v1/seller/products/{other['id']}", json={"seller_sku": taken}, headers=AUTH
    )

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELLER_SKU_ALREADY_EXISTS"


# ── Фотографии ───────────────────────────────────────────────────────────────

JPEG = b"\xff\xd8\xff" + b"body"


def with_storage():
    from app.api.v1.photos import get_photo_storage
    from app.platform.photo_storage import PhotoStorage

    class FakeS3Client:
        def put_object(self, **kwargs):
            return None

    app.dependency_overrides[get_photo_storage] = lambda: PhotoStorage(
        bucket="test-bucket", client=FakeS3Client()
    )


def upload(client, seller_product_id, *, data=JPEG, content_type="image/jpeg", name="photo.jpg"):
    import io as _io

    return client.post(
        f"/api/v1/seller/products/{seller_product_id}/photos",
        files={"file": (name, _io.BytesIO(data), content_type)},
        headers=AUTH,
    )


def test_photo_upload_attaches_to_own_product(committing_session):
    """Загрузка и привязка одним запросом: без привязки Seller Admin не может
    довести новый товар до витрины."""
    seller_id = insert_seller(committing_session, name="Ферма фото API")
    user_id = insert_user(committing_session, name="Пользователь фото API")
    offer = add_offer(committing_session, seller_id, name="Товар фото API")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()

    response = upload(client, offer.id)

    app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["seller_product_id"] == offer.id
    assert body["sort_order"] == 0
    assert body["url"]


def test_photo_upload_appends_to_the_end_of_gallery(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма порядка фото")
    user_id = insert_user(committing_session, name="Пользователь порядка фото")
    offer = add_offer(committing_session, seller_id, name="Товар порядка фото")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()

    upload(client, offer.id)
    second = upload(client, offer.id)

    app.dependency_overrides.clear()
    assert second.json()["sort_order"] == 1


def test_photo_upload_to_foreign_product_is_not_found(committing_session):
    mine = insert_seller(committing_session, name="Ферма своя фото")
    theirs = insert_seller(committing_session, name="Ферма чужая фото")
    user_id = insert_user(committing_session, name="Пользователь чужого фото")
    foreign = add_offer(committing_session, theirs, name="Чужой товар фото")
    client = client_for(committing_session, mine, user_id)
    with_storage()

    response = upload(client, foreign.id)

    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_photo_upload_rejects_unsupported_content_type(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма типа фото")
    user_id = insert_user(committing_session, name="Пользователь типа фото")
    offer = add_offer(committing_session, seller_id, name="Товар типа фото")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()

    response = upload(client, offer.id, data=b"%PDF-1.4", content_type="application/pdf", name="doc.pdf")

    app.dependency_overrides.clear()
    assert response.status_code == 415


def test_photo_upload_rejects_payload_not_matching_type(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма подделки фото")
    user_id = insert_user(committing_session, name="Пользователь подделки фото")
    offer = add_offer(committing_session, seller_id, name="Товар подделки фото")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()

    response = upload(client, offer.id, data=b"%PDF-1.4 not an image")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE_PAYLOAD"


def test_photo_upload_rejects_oversized_file(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма размера фото")
    user_id = insert_user(committing_session, name="Пользователь размера фото")
    offer = add_offer(committing_session, seller_id, name="Товар размера фото")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()

    response = upload(client, offer.id, data=JPEG + b"x" * (10 * 1024 * 1024))

    app.dependency_overrides.clear()
    assert response.status_code == 413


def test_photo_upload_without_token_returns_401(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма фото без токена")
    user_id = insert_user(committing_session, name="Пользователь фото без токена")
    offer = add_offer(committing_session, seller_id, name="Товар фото без токена")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()
    import io as _io

    response = client.post(
        f"/api/v1/seller/products/{offer.id}/photos",
        files={"file": ("photo.jpg", _io.BytesIO(JPEG), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_uploaded_photo_appears_in_product_detail(committing_session):
    """Сквозной кусок сценария ТЗ: создать товар, загрузить фото — карточка
    отдаёт его ссылкой."""
    seller_id = insert_seller(committing_session, name="Ферма сквозного фото")
    user_id = insert_user(committing_session, name="Пользователь сквозного фото")
    client = client_for(committing_session, seller_id, user_id)
    with_storage()
    created = client.post("/api/v1/seller/products", json=NEW_PRODUCT, headers=AUTH).json()

    upload(client, created["id"])
    detail = client.get(f"/api/v1/seller/products/{created['id']}", headers=AUTH).json()

    app.dependency_overrides.clear()
    assert len(detail["photos"]) == 1

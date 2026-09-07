"""Публикация каталога из Seller Admin.

Ключевое отличие от публикации из книги: seller-путь работает с уже
сохранённым состоянием SellerProduct и никогда не снимает товар с витрины
только потому, что его нет во входном наборе. Входного набора здесь вообще нет
— публикуется то, что лежит в каталоге продавца.
"""

import uuid

from sqlalchemy import text

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.seller_gateway import SellerGateway
from app.publication.seller_catalog_publisher import SellerCatalogPublisher


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid


def make_publisher(session) -> SellerCatalogPublisher:
    return SellerCatalogPublisher(
        session=session,
        seller_gateway=SellerGateway(session),
        seller_product_repository=SellerProductRepository(session),
        seller_product_photo_repository=SellerProductPhotoRepository(session),
        catalog_publication_repository=CatalogPublicationRepository(session),
    )


def insert_photo(session, *, seller_id: int) -> int:
    """Настоящая строка Photo: SellerProductPhoto.photo_id — внешний ключ на неё.

    Ключ уникален в схеме, поэтому у каждой фотографии он свой."""
    return session.execute(
        text("INSERT INTO Photo (s3_key, seller_id) VALUES (:key, :seller_id)"),
        {"key": f"greenmarket/seller-products/{uuid.uuid4()}.jpg", "seller_id": seller_id},
    ).lastrowid


def add_offer(session, seller_id, *, name: str, price=100, with_photo=False, is_published=False):
    offer = SellerProductRepository(session).create(
        seller_id=seller_id, product_id=None, seller_name=name,
        price=price, stock=1, unit="кг", description=None, is_published=is_published,
    )
    if with_photo:
        photo_id = insert_photo(session, seller_id=seller_id)
        SellerProductPhotoRepository(session).replace_for_product(offer.id, [photo_id])
    return offer


def published_flag(session, offer_id: int) -> bool:
    return bool(
        session.execute(
            text("SELECT is_published FROM SellerProduct WHERE id = :id"), {"id": offer_id}
        ).scalar()
    )


def test_publish_empty_catalog_succeeds_and_creates_publication(committing_session):
    """Продавец без единого товара публикуется штатно — ТЗ, «Публикация пустого
    каталога»: это допустимая операция, а не ошибка."""
    seller_id = insert_seller(committing_session, name="Ферма без товаров")
    user_id = insert_user(committing_session, name="Пользователь пустого каталога")

    result = make_publisher(committing_session).publish(seller_id, published_by=user_id)

    assert result.success is True
    assert result.created_count == 0
    assert result.updated_count == 0
    assert result.deactivated_count == 0
    version = committing_session.execute(
        text("SELECT version FROM CatalogPublication WHERE seller_id = :s"), {"s": seller_id}
    ).scalar()
    assert version == 1


def test_publish_does_not_deactivate_product_absent_from_request(committing_session):
    """Обязательный regression-тест ТЗ: есть A и B, меняем только A, публикуем —
    B остаётся на витрине.

    Именно так seller-путь отличается от публикации из книги, где строка,
    пропавшая из входного набора, снимается с публикации.
    """
    seller_id = insert_seller(committing_session, name="Ферма двух товаров")
    user_id = insert_user(committing_session, name="Пользователь двух товаров")
    a = add_offer(committing_session, seller_id, name="Товар A", with_photo=True, is_published=True)
    b = add_offer(committing_session, seller_id, name="Товар B", with_photo=True, is_published=True)
    publisher = make_publisher(committing_session)
    publisher.publish(seller_id, published_by=user_id)

    a.price = 999
    committing_session.flush()
    publisher.publish(seller_id, published_by=user_id)

    assert published_flag(committing_session, b.id) is True
    assert published_flag(committing_session, a.id) is True


def test_publish_hides_offer_without_photo(committing_session):
    """Товар без фотографии покупателю не показывается, но из каталога продавца
    никуда не девается (Publication_Model.md)."""
    seller_id = insert_seller(committing_session, name="Ферма без фото")
    user_id = insert_user(committing_session, name="Пользователь без фото")
    offer = add_offer(committing_session, seller_id, name="Товар без фото", is_published=True)

    result = make_publisher(committing_session).publish(seller_id, published_by=user_id)

    assert published_flag(committing_session, offer.id) is False
    assert result.deactivated_count == 1
    assert "Товар без фото" in result.hidden_no_photo
    assert SellerProductRepository(committing_session).find_by_id(offer.id) is not None


def test_publish_shows_offer_after_photo_added(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма с фото")
    user_id = insert_user(committing_session, name="Пользователь с фото")
    offer = add_offer(committing_session, seller_id, name="Товар с фото", with_photo=True, is_published=False)

    result = make_publisher(committing_session).publish(seller_id, published_by=user_id)

    assert published_flag(committing_session, offer.id) is True
    assert result.updated_count == 1
    assert result.hidden_no_photo == []


def test_publish_bumps_version_and_records_seller_state(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма версий")
    user_id = insert_user(committing_session, name="Пользователь версий")
    add_offer(committing_session, seller_id, name="Товар версий", with_photo=True, is_published=True)
    publisher = make_publisher(committing_session)

    first = publisher.publish(seller_id, published_by=user_id)
    second = publisher.publish(seller_id, published_by=user_id)

    assert first.publication_key != second.publication_key
    row = committing_session.execute(
        text("SELECT current_catalog_version, current_publication_key, current_catalog_hash "
             "FROM Seller WHERE id = :s"),
        {"s": seller_id},
    ).one()
    assert row[0] == 2
    assert row[1] == second.publication_key
    assert row[2] == second.catalog_hash


def test_second_publish_without_changes_still_creates_publication(committing_session):
    """ТЗ, Double Publish: требования идемпотентности нет — каждая успешная
    публикация получает собственную запись и следующую версию, даже если
    состояние каталога не изменилось."""
    seller_id = insert_seller(committing_session, name="Ферма двойной публикации")
    user_id = insert_user(committing_session, name="Пользователь двойной публикации")
    add_offer(committing_session, seller_id, name="Товар двойной публикации", with_photo=True, is_published=True)
    publisher = make_publisher(committing_session)

    publisher.publish(seller_id, published_by=user_id)
    publisher.publish(seller_id, published_by=user_id)

    versions = [
        row[0]
        for row in committing_session.execute(
            text("SELECT version FROM CatalogPublication WHERE seller_id = :s ORDER BY version"), {"s": seller_id}
        ).all()
    ]
    assert versions == [1, 2]


# ── Эндпоинт ─────────────────────────────────────────────────────────────────


def override_bearer_access(seller_id: int, published_by: int, *, valid_token: str = "seller-bearer-token"):
    from fastapi import Header

    from app.api.v1.seller import get_seller_bearer_access
    from app.main import app
    from app.publication.seller_access import SellerAccess

    def resolver(authorization: str | None = Header(default=None)):
        if authorization is None or authorization.lower() != f"bearer {valid_token}":
            return None
        return SellerAccess(seller_id=seller_id, published_by=published_by, name="Продавец")

    app.dependency_overrides[get_seller_bearer_access] = resolver


def publish_client(session):
    from app.infrastructure.database import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: (yield session)
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_publish_endpoint_returns_200_for_valid_bearer_token(committing_session):
    from app.main import app

    seller_id = insert_seller(committing_session, name="Ферма эндпоинта")
    user_id = insert_user(committing_session, name="Пользователь эндпоинта")
    add_offer(committing_session, seller_id, name="Товар эндпоинта", with_photo=True)
    override_bearer_access(seller_id, user_id)
    client = publish_client(committing_session)

    response = client.post(
        "/api/v1/seller/catalog/publish", headers={"Authorization": "Bearer seller-bearer-token"}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["updated"] == 1


def test_publish_endpoint_without_token_returns_401(committing_session):
    from app.main import app

    seller_id = insert_seller(committing_session, name="Ферма без токена")
    user_id = insert_user(committing_session, name="Пользователь без токена")
    override_bearer_access(seller_id, user_id)
    client = publish_client(committing_session)

    response = client.post("/api/v1/seller/catalog/publish")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_publish_endpoint_does_not_accept_token_in_query(committing_session):
    """ТЗ, раздел 10: аутентификация не передаётся ни в query, ни в теле."""
    from app.main import app

    seller_id = insert_seller(committing_session, name="Ферма query-токена")
    user_id = insert_user(committing_session, name="Пользователь query-токена")
    override_bearer_access(seller_id, user_id)
    client = publish_client(committing_session)

    response = client.post("/api/v1/seller/catalog/publish?access_token=seller-bearer-token")

    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_publish_endpoint_with_empty_catalog_returns_200(committing_session):
    from app.main import app

    seller_id = insert_seller(committing_session, name="Ферма пустого эндпоинта")
    user_id = insert_user(committing_session, name="Пользователь пустого эндпоинта")
    override_bearer_access(seller_id, user_id)
    client = publish_client(committing_session)

    response = client.post(
        "/api/v1/seller/catalog/publish", headers={"Authorization": "Bearer seller-bearer-token"}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["updated"] == 0

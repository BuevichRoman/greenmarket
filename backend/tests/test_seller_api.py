from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.publications import get_seller_access_resolver
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.main import app
from app.publication.seller_access import SellerAccess

VALID_TOKEN = "seller-api-test-token"


def override_seller_access(seller_id: int, published_by: int) -> None:
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name="Тестовый продавец")
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: access if token == VALID_TOKEN else None)


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def test_get_seller_catalog_returns_status_for_never_published_seller(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец без публикаций API")
    override_session(committing_session)
    override_seller_access(seller_id, seller_id)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["current_catalog_version"] == 0
    assert body["published_product_count"] == 0
    assert body["last_published_at"] is None


def test_get_seller_catalog_reflects_real_publication(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с публикацией API")
    user_id = insert_user(committing_session, name="Admin API")
    CatalogPublicationRepository(committing_session).create(
        seller_id=seller_id, version=1, publication_key="seller-api-key", catalog_hash="seller-api-hash",
        published_by=user_id, created_count=2,
    )
    committing_session.execute(text("UPDATE Seller SET current_catalog_version = 1 WHERE id = :id"), {"id": seller_id})
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["current_catalog_version"] == 1
    assert body["last_published_at"] is not None


def test_get_seller_catalog_rejects_invalid_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": "not-a-real-token"})

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_get_seller_catalog_returns_404_for_token_with_no_seller_row(committing_session):
    # Токен резолвится (не 403), но указывает на несуществующий seller_id —
    # ошибка конфигурации SELLER_ACCESS_TOKENS, а не проблема доступа.
    override_session(committing_session)
    override_seller_access(999_999, 1)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"

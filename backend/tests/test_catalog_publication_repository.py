from sqlalchemy import text

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository


def insert_seller_and_user(session, *, name: str) -> tuple[int, int]:
    seller_id = session.execute(text("INSERT INTO Seller (name) VALUES (:name)"), {"name": name}).lastrowid
    user_id = session.execute(text("INSERT INTO User (name) VALUES (:name)"), {"name": "Admin"}).lastrowid
    return seller_id, user_id


def test_latest_version_is_zero_when_seller_never_published(session):
    seller_id, _ = insert_seller_and_user(session, name="Продавец без публикаций")
    repository = CatalogPublicationRepository(session)

    assert repository.latest_version(seller_id) == 0


def test_create_persists_publication_and_latest_version_increases(session):
    seller_id, user_id = insert_seller_and_user(session, name="Продавец с публикацией")
    repository = CatalogPublicationRepository(session)

    repository.create(seller_id=seller_id, version=1, publication_key="key-1", catalog_hash="hash-1", published_by=user_id)

    assert repository.latest_version(seller_id) == 1


def test_latest_version_is_scoped_per_seller(session):
    seller_a, user_id = insert_seller_and_user(session, name="Продавец A")
    seller_b, _ = insert_seller_and_user(session, name="Продавец Б")
    repository = CatalogPublicationRepository(session)
    repository.create(seller_id=seller_a, version=1, publication_key="key-a1", catalog_hash="hash-a1", published_by=user_id)
    repository.create(seller_id=seller_a, version=2, publication_key="key-a2", catalog_hash="hash-a2", published_by=user_id)

    assert repository.latest_version(seller_a) == 2
    assert repository.latest_version(seller_b) == 0


def test_exists_with_key_true_after_create_false_before(session):
    seller_id, user_id = insert_seller_and_user(session, name="Продавец для ключа")
    repository = CatalogPublicationRepository(session)

    assert repository.exists_with_key("unique-key-1") is False

    repository.create(seller_id=seller_id, version=1, publication_key="unique-key-1", catalog_hash="hash-1", published_by=user_id)

    assert repository.exists_with_key("unique-key-1") is True

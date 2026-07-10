from sqlalchemy import text

from app.platform.seller_gateway import SellerGateway


def insert_seller(session, *, name: str, publication_key: str | None, catalog_hash: str | None) -> int:
    result = session.execute(
        text(
            "INSERT INTO Seller (name, current_publication_key, current_catalog_hash) "
            "VALUES (:name, :publication_key, :catalog_hash)"
        ),
        {"name": name, "publication_key": publication_key, "catalog_hash": catalog_hash},
    )
    return result.lastrowid


def test_returns_current_publication_key_for_published_seller(session):
    seller_id = insert_seller(session, name="Фермер Иванов", publication_key="key-123", catalog_hash="hash-abc")

    assert SellerGateway(session).get_current_publication_key(seller_id) == "key-123"


def test_returns_current_catalog_hash_for_published_seller(session):
    seller_id = insert_seller(session, name="Фермер Петров", publication_key="key-456", catalog_hash="hash-def")

    assert SellerGateway(session).get_current_catalog_hash(seller_id) == "hash-def"


def test_returns_none_when_seller_never_published(session):
    seller_id = insert_seller(session, name="Новый продавец", publication_key=None, catalog_hash=None)

    gateway = SellerGateway(session)
    assert gateway.get_current_publication_key(seller_id) is None
    assert gateway.get_current_catalog_hash(seller_id) is None


def test_returns_none_for_missing_seller(session):
    gateway = SellerGateway(session)
    assert gateway.get_current_publication_key(999_999) is None
    assert gateway.get_current_catalog_hash(999_999) is None

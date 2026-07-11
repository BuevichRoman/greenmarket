from sqlalchemy import text

from app.infrastructure.repositories.seller_product_repository import SellerProductRepository


def insert_seller(session, *, name: str) -> int:
    result = session.execute(text("INSERT INTO Seller (name) VALUES (:name)"), {"name": name})
    return result.lastrowid


def test_create_persists_and_returns_seller_product_with_id(session):
    seller_id = insert_seller(session, name="Ферма создание")
    repository = SellerProductRepository(session)

    created = repository.create(
        seller_id=seller_id, product_id=None, seller_name="Ферма А",
        price=50, stock=5, unit="кг", description=None,
    )

    assert created.id is not None
    assert created.seller_id == seller_id
    assert created.seller_name == "Ферма А"


def test_list_by_seller_returns_only_that_sellers_products(session):
    seller_a = insert_seller(session, name="Продавец А")
    seller_b = insert_seller(session, name="Продавец Б")
    repository = SellerProductRepository(session)
    repository.create(seller_id=seller_a, product_id=None, seller_name="Товар А1", price=1, stock=1, unit="шт", description=None)
    repository.create(seller_id=seller_b, product_id=None, seller_name="Товар Б1", price=2, stock=2, unit="шт", description=None)

    result = repository.list_by_seller(seller_a)

    assert len(result) == 1
    assert result[0].seller_name == "Товар А1"


def test_find_by_id_returns_created_seller_product(session):
    seller_id = insert_seller(session, name="Продавец В")
    repository = SellerProductRepository(session)
    created = repository.create(seller_id=seller_id, product_id=None, seller_name="Товар В1", price=3, stock=3, unit="шт", description=None)

    found = repository.find_by_id(created.id)

    assert found is not None
    assert found.seller_name == "Товар В1"


def test_find_by_id_returns_none_for_missing_id(session):
    repository = SellerProductRepository(session)
    assert repository.find_by_id(999_999) is None

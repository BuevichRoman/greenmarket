from sqlalchemy import text

from app.infrastructure.repositories.seller_product_repository import SellerProductRepository


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    result = session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id})
    return result.lastrowid


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid


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


def test_list_published_for_products_excludes_unpublished(session):
    group_id = insert_product_group(session, name="Группа для published-фильтра")
    product_id = insert_product(session, group_id=group_id, name="Товар для published-фильтра")
    seller_id = insert_seller(session, name="Продавец для published-фильтра")
    repository = SellerProductRepository(session)
    published = repository.create(
        seller_id=seller_id, product_id=product_id, seller_name="Опубликован", price=10, stock=1, unit="шт", description=None,
    )
    unpublished = repository.create(
        seller_id=seller_id, product_id=product_id, seller_name="Не опубликован", price=20, stock=1, unit="шт", description=None,
    )
    session.execute(
        text("UPDATE SellerProduct SET is_published = FALSE WHERE id = :id"),
        {"id": unpublished.id},
    )

    result = repository.list_published_for_products([product_id])

    ids = [sp.id for sp in result]
    assert published.id in ids
    assert unpublished.id not in ids


def test_list_published_for_products_filters_by_product_id(session):
    group_id = insert_product_group(session, name="Группа для product_id-фильтра")
    product_a_id = insert_product(session, group_id=group_id, name="Товар A для product_id-фильтра")
    product_b_id = insert_product(session, group_id=group_id, name="Товар B для product_id-фильтра")
    seller_id = insert_seller(session, name="Продавец для product_id-фильтра")
    repository = SellerProductRepository(session)
    for_product_a = repository.create(
        seller_id=seller_id, product_id=product_a_id, seller_name="Товар A", price=10, stock=1, unit="шт", description=None,
    )
    repository.create(
        seller_id=seller_id, product_id=product_b_id, seller_name="Товар B", price=10, stock=1, unit="шт", description=None,
    )

    result = repository.list_published_for_products([product_a_id])

    assert [sp.id for sp in result] == [for_product_a.id]


def test_list_published_for_products_returns_empty_list_for_empty_input(session):
    assert SellerProductRepository(session).list_published_for_products([]) == []


def test_count_published_counts_only_published(session):
    seller_id = insert_seller(session, name="Продавец для count_published")
    repository = SellerProductRepository(session)
    repository.create(seller_id=seller_id, product_id=None, seller_name="Опубликован для count", price=1, stock=1, unit="шт", description=None)
    unpublished = repository.create(seller_id=seller_id, product_id=None, seller_name="Не опубликован для count", price=1, stock=1, unit="шт", description=None)
    session.execute(text("UPDATE SellerProduct SET is_published = FALSE WHERE id = :id"), {"id": unpublished.id})

    assert repository.count_published(seller_id) == 1


def test_count_published_returns_zero_for_seller_without_products(session):
    seller_id = insert_seller(session, name="Продавец без товаров для count_published")
    assert SellerProductRepository(session).count_published(seller_id) == 0


def test_count_published_only_counts_the_given_seller(session):
    seller_a = insert_seller(session, name="Продавец А для count_published изоляции")
    seller_b = insert_seller(session, name="Продавец Б для count_published изоляции")
    repository = SellerProductRepository(session)
    repository.create(seller_id=seller_a, product_id=None, seller_name="Товар А", price=1, stock=1, unit="шт", description=None)
    repository.create(seller_id=seller_b, product_id=None, seller_name="Товар Б", price=1, stock=1, unit="шт", description=None)

    assert repository.count_published(seller_a) == 1

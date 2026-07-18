from sqlalchemy import text

from app.application.catalog_use_case import CatalogUseCase


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


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
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец', :price, 'шт')"
        ),
        {"seller_id": seller_id, "product_id": product_id, "price": price},
    ).lastrowid


def test_list_groups_counts_only_products_with_visible_offers(session):
    group_with_offer = insert_product_group(session, name="Группа с предложением")
    group_without_offer = insert_product_group(session, name="Группа без предложений")
    product_with_offer = insert_product(session, group_id=group_with_offer, name="Товар с предложением")
    insert_product(session, group_id=group_without_offer, name="Товар без предложений")
    seller_id = insert_active_seller(session, name="Продавец для list_groups")
    insert_seller_product(session, seller_id=seller_id, product_id=product_with_offer, price=10)

    groups = {g["id"]: g for g in CatalogUseCase(session).list_groups()}

    assert groups[group_with_offer]["product_count"] == 1
    assert groups[group_without_offer]["product_count"] == 0


def test_list_groups_excludes_offers_from_inactive_sellers(session):
    group_id = insert_product_group(session, name="Группа с неактивным продавцом")
    product_id = insert_product(session, group_id=group_id, name="Товар неактивного продавца")
    seller_id = insert_active_seller(session, name="Скоро неактивный продавец")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    groups = {g["id"]: g for g in CatalogUseCase(session).list_groups()}

    assert groups[group_id]["product_count"] == 0


def test_list_products_returns_min_price_and_offer_count(session):
    group_id = insert_product_group(session, name="Группа для min_price")
    product_id = insert_product(session, group_id=group_id, name="Товар с двумя предложениями")
    seller_a = insert_active_seller(session, name="Продавец подороже")
    seller_b = insert_active_seller(session, name="Продавец подешевле")
    insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=100)
    insert_seller_product(session, seller_id=seller_b, product_id=product_id, price=50)

    items, total = CatalogUseCase(session).list_products()

    item = next(i for i in items if i["id"] == product_id)
    assert item["min_price"] == 50
    assert item["offer_count"] == 2
    assert total >= 1


def test_list_products_excludes_products_without_visible_offers(session):
    group_id = insert_product_group(session, name="Группа без видимых товаров")
    product_id = insert_product(session, group_id=group_id, name="Товар без предложений list_products")

    items, _ = CatalogUseCase(session).list_products()

    assert product_id not in [i["id"] for i in items]


def test_list_products_filters_by_group_id(session):
    group_a = insert_product_group(session, name="Группа A для list_products фильтра")
    group_b = insert_product_group(session, name="Группа B для list_products фильтра")
    product_a = insert_product(session, group_id=group_a, name="Товар группы A list_products")
    product_b = insert_product(session, group_id=group_b, name="Товар группы B list_products")
    seller_id = insert_active_seller(session, name="Продавец для группового фильтра")
    insert_seller_product(session, seller_id=seller_id, product_id=product_a, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=product_b, price=10)

    items, _ = CatalogUseCase(session).list_products(group_id=group_a)

    ids = [i["id"] for i in items]
    assert product_a in ids
    assert product_b not in ids


def test_list_products_filters_by_search(session):
    # Seed data (database/seeders/002_products.sql) has a product literally named
    # "Яблоко", but seeders only cover ProductGroup/Product — no SellerProduct rows
    # exist in seed data, so the seeded "Яблоко" has no visible offer and can never
    # appear in list_products results. No collision with this test's own "Яблоко".
    group_id = insert_product_group(session, name="Группа для поиска list_products")
    apple_id = insert_product(session, group_id=group_id, name="Яблоко Симиренко")
    pear_id = insert_product(session, group_id=group_id, name="Груша Дюшес")
    seller_id = insert_active_seller(session, name="Продавец для поиска list_products")
    insert_seller_product(session, seller_id=seller_id, product_id=apple_id, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=pear_id, price=10)

    items, _ = CatalogUseCase(session).list_products(search="яблоко")

    ids = [i["id"] for i in items]
    assert apple_id in ids
    assert pear_id not in ids


def test_list_products_sorts_by_price_when_requested(session):
    group_id = insert_product_group(session, name="Группа для сортировки по цене")
    cheap_id = insert_product(session, group_id=group_id, name="Дешёвый товар sort")
    expensive_id = insert_product(session, group_id=group_id, name="Дорогой товар sort")
    seller_id = insert_active_seller(session, name="Продавец для сортировки")
    insert_seller_product(session, seller_id=seller_id, product_id=cheap_id, price=5)
    insert_seller_product(session, seller_id=seller_id, product_id=expensive_id, price=500)

    items, _ = CatalogUseCase(session).list_products(sort="price", group_id=group_id)

    assert [i["id"] for i in items] == [cheap_id, expensive_id]


def test_list_products_paginates(session):
    group_id = insert_product_group(session, name="Группа для пагинации")
    seller_id = insert_active_seller(session, name="Продавец для пагинации")
    product_ids = []
    for i in range(3):
        pid = insert_product(session, group_id=group_id, name=f"Товар пагинации {i}")
        insert_seller_product(session, seller_id=seller_id, product_id=pid, price=10)
        product_ids.append(pid)

    page_1, total = CatalogUseCase(session).list_products(group_id=group_id, page=1, limit=2)
    page_2, _ = CatalogUseCase(session).list_products(group_id=group_id, page=2, limit=2)

    assert total == 3
    assert len(page_1) == 2
    assert len(page_2) == 1


def test_get_product_returns_offers_sorted_by_price(session):
    group_id = insert_product_group(session, name="Группа для get_product")
    product_id = insert_product(session, group_id=group_id, name="Товар для get_product")
    seller_expensive = insert_active_seller(session, name="Дорогой продавец get_product")
    seller_cheap = insert_active_seller(session, name="Дешёвый продавец get_product")
    insert_seller_product(session, seller_id=seller_expensive, product_id=product_id, price=200)
    insert_seller_product(session, seller_id=seller_cheap, product_id=product_id, price=20)

    result = CatalogUseCase(session).get_product(product_id)

    assert result is not None
    assert result["id"] == product_id
    assert [offer["price"] for offer in result["offers"]] == [20, 200]


def test_get_product_returns_none_for_product_without_visible_offers(session):
    group_id = insert_product_group(session, name="Группа для get_product без предложений")
    product_id = insert_product(session, group_id=group_id, name="Товар без предложений get_product")

    assert CatalogUseCase(session).get_product(product_id) is None


def test_get_product_returns_none_for_missing_product(session):
    assert CatalogUseCase(session).get_product(999_999) is None

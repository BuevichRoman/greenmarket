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

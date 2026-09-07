"""Каталог продавца для Seller Admin — своя выборка, не покупательская.

Продавец обязан видеть каталог целиком: и непромодерированные позиции, и
снятые с витрины. Покупательская `list_visible_for_seller` для этого не годится
— она по определению показывает только видимое.
"""

import uuid

from sqlalchemy import text

from app.infrastructure.repositories.seller_product_repository import SellerProductRepository


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_group(session, *, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name, is_active) VALUES (:name, :is_active)"),
        {"name": name, "is_active": is_active},
    ).lastrowid


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:g, :n)"),
        {"g": group_id, "n": f"{name} {uuid.uuid4().hex[:6]}"},
    ).lastrowid


def add_offer(session, seller_id, *, name, product_id=None, price=100, stock=1, is_published=False, sku=None):
    return SellerProductRepository(session).create(
        seller_id=seller_id, product_id=product_id, seller_name=name,
        price=price, stock=stock, unit="кг", description=None,
        is_published=is_published, seller_sku=sku,
    )


def test_list_for_seller_admin_shows_unmoderated_and_hidden_rows(session):
    """Продавцу видно всё своё: и без связи со справочником, и снятое с витрины."""
    seller_id = insert_seller(session, name="Ферма полного списка")
    hidden = add_offer(session, seller_id, name="Снятый с витрины", is_published=False)
    unmoderated = add_offer(session, seller_id, name="Ждёт модерации", is_published=True)

    items, total = SellerProductRepository(session).list_for_seller_admin(seller_id, page=1, page_size=50)

    ids = {row.id for row, _, _ in items}
    assert hidden.id in ids
    assert unmoderated.id in ids
    assert total == 2


def test_list_for_seller_admin_never_returns_other_sellers_rows(session):
    mine = insert_seller(session, name="Ферма своя")
    theirs = insert_seller(session, name="Ферма чужая")
    add_offer(session, theirs, name="Чужой товар")
    my_offer = add_offer(session, mine, name="Свой товар")

    items, total = SellerProductRepository(session).list_for_seller_admin(mine, page=1, page_size=50)

    assert [row.id for row, _, _ in items] == [my_offer.id]
    assert total == 1


def test_list_for_seller_admin_returns_global_names_and_null_when_unmoderated(session):
    seller_id = insert_seller(session, name="Ферма имён")
    group_id = insert_group(session, name="Группа имён")
    product_id = insert_product(session, group_id=group_id, name="Эталонное имя")
    add_offer(session, seller_id, name="Своё имя", product_id=product_id)
    add_offer(session, seller_id, name="Без справочника")

    items, _ = SellerProductRepository(session).list_for_seller_admin(seller_id, page=1, page_size=50)
    by_name = {row.seller_name: (product, group) for row, product, group in items}

    assert by_name["Своё имя"][0] is not None
    assert by_name["Своё имя"][1].name == "Группа имён"
    assert by_name["Без справочника"] == (None, None)


def test_list_for_seller_admin_filters_by_published_flag(session):
    seller_id = insert_seller(session, name="Ферма фильтра публикации")
    shown = add_offer(session, seller_id, name="Опубликован фильтр", is_published=True)
    add_offer(session, seller_id, name="Не опубликован фильтр", is_published=False)

    items, total = SellerProductRepository(session).list_for_seller_admin(
        seller_id, page=1, page_size=50, is_published=True
    )

    assert [row.id for row, _, _ in items] == [shown.id]
    assert total == 1


def test_list_for_seller_admin_filters_by_moderation_status(session):
    seller_id = insert_seller(session, name="Ферма фильтра модерации")
    group_id = insert_group(session, name="Группа фильтра модерации")
    product_id = insert_product(session, group_id=group_id, name="Позиция фильтра модерации")
    resolved = add_offer(session, seller_id, name="Сопоставлен", product_id=product_id)
    add_offer(session, seller_id, name="Ждёт позиции")

    items, total = SellerProductRepository(session).list_for_seller_admin(
        seller_id, page=1, page_size=50, moderation_status="RESOLVED"
    )

    assert [row.id for row, _, _ in items] == [resolved.id]
    assert total == 1


def test_list_for_seller_admin_search_matches_both_names(session):
    """Поиск идёт по обоим именам — своему и эталонному, как в каталоге продавца."""
    seller_id = insert_seller(session, name="Ферма поиска админки")
    group_id = insert_group(session, name="Группа поиска админки")
    product_id = insert_product(session, group_id=group_id, name="Клюква эталонная админка")
    offer = add_offer(session, seller_id, name="Клюква вяленая своя админка", product_id=product_id)
    add_offer(session, seller_id, name="Огурцы посторонние админка")

    items, _ = SellerProductRepository(session).list_for_seller_admin(
        seller_id, page=1, page_size=50, search="вяленая эталонная"
    )

    assert [row.id for row, _, _ in items] == [offer.id]


def test_list_for_seller_admin_sorts_by_price_descending(session):
    seller_id = insert_seller(session, name="Ферма сортировки")
    cheap = add_offer(session, seller_id, name="Дешёвый", price=10)
    pricey = add_offer(session, seller_id, name="Дорогой", price=990)

    items, _ = SellerProductRepository(session).list_for_seller_admin(
        seller_id, page=1, page_size=50, sort="-price"
    )

    assert [row.id for row, _, _ in items] == [pricey.id, cheap.id]


def test_list_for_seller_admin_paginates(session):
    seller_id = insert_seller(session, name="Ферма страниц")
    for index in range(3):
        add_offer(session, seller_id, name=f"Товар страницы {index}", price=index + 1)

    page_two, total = SellerProductRepository(session).list_for_seller_admin(
        seller_id, page=2, page_size=2, sort="price"
    )

    assert total == 3
    assert len(page_two) == 1


def test_list_for_seller_admin_page_beyond_total_is_empty_not_error(session):
    seller_id = insert_seller(session, name="Ферма пустой страницы")
    add_offer(session, seller_id, name="Единственный товар")

    items, total = SellerProductRepository(session).list_for_seller_admin(seller_id, page=99, page_size=50)

    assert items == []
    assert total == 1

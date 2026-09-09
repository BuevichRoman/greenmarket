"""Сортировка каталога по дате поставки — «посмотреть свежее».

NULL всегда в конце, в обе стороны: товар без даты не «самый старый» и не
«самый свежий», он просто без даты, и подмешивать его в середину выдачи нельзя.
"""

import uuid
from datetime import date

from sqlalchemy import text

from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:n)"), {"n": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:u)"), {"u": user_id}).lastrowid


def insert_group(session, *, name: str) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name) VALUES (:n)"), {"n": f"{name} {uuid.uuid4().hex[:6]}"}
    ).lastrowid


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:g, :n)"),
        {"g": group_id, "n": f"{name} {uuid.uuid4().hex[:6]}"},
    ).lastrowid


def insert_photo(session, *, seller_id: int) -> int:
    return session.execute(
        text("INSERT INTO Photo (s3_key, seller_id) VALUES (:k, :s)"),
        {"k": f"greenmarket/seller-products/{uuid.uuid4()}.jpg", "s": seller_id},
    ).lastrowid


def add_visible_offer(session, seller_id, product_id, *, name, price=100, supply_date=None):
    """Видимое покупателю предложение: опубликованное и с фотографией."""
    offer = SellerProductRepository(session).create(
        seller_id=seller_id, product_id=product_id, seller_name=name, price=price, stock=1,
        unit="кг", description=None, is_published=True, supply_date=supply_date,
    )
    from app.infrastructure.repositories.seller_product_photo_repository import (
        SellerProductPhotoRepository,
    )

    SellerProductPhotoRepository(session).replace_for_product(
        offer.id, [insert_photo(session, seller_id=seller_id)]
    )
    return offer


def build_catalog(session, *, prefix: str):
    """Четыре товара: три с датами, один без."""
    seller_id = insert_seller(session, name=f"Ферма {prefix}")
    group_id = insert_group(session, name=f"Группа {prefix}")
    dates = [date(2026, 9, 10), date(2026, 9, 12), date(2026, 9, 15), None]
    products = []
    for index, supply in enumerate(dates):
        product_id = insert_product(session, group_id=group_id, name=f"Товар {prefix} {index}")
        add_visible_offer(
            session, seller_id, product_id, name=f"Предложение {prefix} {index}", supply_date=supply
        )
        products.append(product_id)
    return seller_id, group_id, products, dates


# ── Общий каталог ────────────────────────────────────────────────────────────


def test_global_catalog_returns_supply_date(session):
    _, group_id, products, _ = build_catalog(session, prefix="дата в ответе")

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_id])

    by_id = {item["id"]: item for item in items}
    assert by_id[products[0]]["supply_date"] == date(2026, 9, 10)
    assert by_id[products[3]]["supply_date"] is None


def test_global_catalog_sorts_by_delivery_ascending_with_nulls_last(session):
    _, group_id, products, _ = build_catalog(session, prefix="поставка возр")

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_id], sort="delivery", sort_dir="asc")

    assert [item["id"] for item in items] == products


def test_global_catalog_sorts_by_delivery_descending_with_nulls_last(session):
    _, group_id, products, _ = build_catalog(session, prefix="поставка убыв")

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_id], sort="delivery", sort_dir="desc")

    assert [item["id"] for item in items] == [products[2], products[1], products[0], products[3]]


def test_global_catalog_paginates_after_sorting(session):
    """Страница берётся из уже отсортированного набора, иначе страницы не
    складываются в единый порядок."""
    _, group_id, products, _ = build_catalog(session, prefix="поставка страницы")

    first, total = CatalogUseCase(session).list_products(
        group_ids=[group_id], sort="delivery", sort_dir="desc", page=1, limit=2
    )
    second, _ = CatalogUseCase(session).list_products(
        group_ids=[group_id], sort="delivery", sort_dir="desc", page=2, limit=2
    )

    assert total == 4
    assert [i["id"] for i in first] == [products[2], products[1]]
    assert [i["id"] for i in second] == [products[0], products[3]]


def test_global_catalog_delivery_order_is_deterministic_on_equal_dates(session):
    """Одинаковая дата — порядок задаётся идентификатором, и он не
    переворачивается вместе с направлением."""
    seller_id = insert_seller(session, name="Ферма одинаковых дат")
    group_id = insert_group(session, name="Группа одинаковых дат")
    same = date(2026, 9, 11)
    ids = []
    for index in range(3):
        product_id = insert_product(session, group_id=group_id, name=f"Товар одинаковой даты {index}")
        add_visible_offer(session, seller_id, product_id, name=f"Предложение {index}", supply_date=same)
        ids.append(product_id)

    ascending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="delivery", sort_dir="asc")[0]
    descending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="delivery", sort_dir="desc")[0]

    assert [i["id"] for i in ascending] == sorted(ids)
    assert [i["id"] for i in descending] == sorted(ids)


def test_global_catalog_delivery_respects_search(session):
    _, group_id, products, _ = build_catalog(session, prefix="поставка поиск")
    target = products[1]
    name = session.execute(text("SELECT name FROM Product WHERE id = :i"), {"i": target}).scalar()

    items, total = CatalogUseCase(session).list_products(
        group_ids=[group_id], search=name, sort="delivery", sort_dir="asc"
    )

    assert total == 1
    assert items[0]["id"] == target


def test_global_catalog_name_sort_supports_direction(session):
    _, group_id, products, _ = build_catalog(session, prefix="имя направление")

    ascending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="name", sort_dir="asc")[0]
    descending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="name", sort_dir="desc")[0]

    assert [i["name"] for i in descending] == list(reversed([i["name"] for i in ascending]))


def test_global_catalog_price_sort_supports_direction(session):
    seller_id = insert_seller(session, name="Ферма цены направление")
    group_id = insert_group(session, name="Группа цены направление")
    for index, price in enumerate([300, 100, 200]):
        product_id = insert_product(session, group_id=group_id, name=f"Товар цены {index}")
        add_visible_offer(session, seller_id, product_id, name=f"Предложение цены {index}", price=price)

    ascending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="price", sort_dir="asc")[0]
    descending = CatalogUseCase(session).list_products(group_ids=[group_id], sort="price", sort_dir="desc")[0]

    assert [float(i["min_price"]) for i in ascending] == [100, 200, 300]
    assert [float(i["min_price"]) for i in descending] == [300, 200, 100]


def test_global_catalog_default_sort_is_unchanged(session):
    """Запросы без sort продолжают приходить по имени."""
    _, group_id, _, _ = build_catalog(session, prefix="умолчание")

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_id])

    assert [i["name"] for i in items] == sorted(i["name"] for i in items)


# ── Каталог продавца ─────────────────────────────────────────────────────────


def test_seller_catalog_sorts_by_delivery_both_directions(session):
    seller_id, group_id, _, _ = build_catalog(session, prefix="продавец поставка")

    ascending = CatalogUseCase(session).list_seller_products(
        seller_id, sort="delivery", sort_dir="asc"
    )[0]
    descending = CatalogUseCase(session).list_seller_products(
        seller_id, sort="delivery", sort_dir="desc"
    )[0]

    assert [i["supply_date"] for i in ascending] == [
        date(2026, 9, 10), date(2026, 9, 12), date(2026, 9, 15), None
    ]
    assert [i["supply_date"] for i in descending] == [
        date(2026, 9, 15), date(2026, 9, 12), date(2026, 9, 10), None
    ]


def test_seller_catalog_delivery_paginates_after_sorting(session):
    seller_id, _, _, _ = build_catalog(session, prefix="продавец страницы")

    first, total = CatalogUseCase(session).list_seller_products(
        seller_id, sort="delivery", sort_dir="asc", page=1, limit=2
    )

    assert total == 4
    assert [i["supply_date"] for i in first] == [date(2026, 9, 10), date(2026, 9, 12)]


# ── HTTP ─────────────────────────────────────────────────────────────────────


def catalog_client(session):
    from fastapi.testclient import TestClient

    from app.infrastructure.database import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: (yield session)
    return TestClient(app), app


def test_http_global_catalog_accepts_delivery_sort(committing_session):
    """Прежде этот запрос отвечал 422 — фронт получал отказ на существующую
    кнопку «Поставка»."""
    _, group_id, products, _ = build_catalog(committing_session, prefix="http общий")
    client, app = catalog_client(committing_session)

    ascending = client.get(f"/api/v1/catalog/products?group_id={group_id}&sort=delivery&sort_dir=asc")
    descending = client.get(f"/api/v1/catalog/products?group_id={group_id}&sort=delivery&sort_dir=desc")

    app.dependency_overrides.clear()
    assert ascending.status_code == 200
    assert descending.status_code == 200
    assert [p["id"] for p in ascending.json()["products"]] == products
    assert [p["supply_date"] for p in ascending.json()["products"]] == [
        "2026-09-10", "2026-09-12", "2026-09-15", None
    ]
    assert [p["id"] for p in descending.json()["products"]][-1] == products[3]


def test_http_seller_catalog_accepts_delivery_sort(committing_session):
    seller_id, _, _, _ = build_catalog(committing_session, prefix="http продавец")
    client, app = catalog_client(committing_session)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}/products?sort=delivery&sort_dir=desc")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [p["supply_date"] for p in response.json()["products"]] == [
        "2026-09-15", "2026-09-12", "2026-09-10", None
    ]


def test_http_unknown_sort_value_is_still_rejected(committing_session):
    """Список значений закрыт: неизвестная сортировка — ошибка, а не тихий
    откат к сортировке по имени."""
    client, app = catalog_client(committing_session)

    response = client.get("/api/v1/catalog/products?sort=freshness")

    app.dependency_overrides.clear()
    assert response.status_code == 422

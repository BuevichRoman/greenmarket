"""Каталог одного продавца (REST_API.md, `GET /catalog/sellers/{id}/products`).

Экран «товары выбранного продавца» на прежнем API не собирался: карточка
продавца отдаёт только профиль, а общий список товаров по продавцу не
фильтруется. Единица выдачи здесь другая, чем в общем каталоге: не товарная
позиция с минимальной ценой, а конкретное предложение продавца — со своим
наименованием, ценой и остатком.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str, is_active: bool = True) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(
        text("INSERT INTO Seller (user_id, is_active) VALUES (:user_id, :is_active)"),
        {"user_id": user_id, "is_active": is_active},
    ).lastrowid


def insert_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid


def insert_offer(
    session,
    *,
    seller_id: int,
    product_id: int | None,
    seller_name: str,
    price: str = "100.00",
    unit: str = "кг",
    stock: str = "5.000",
    is_published: bool = True,
) -> int:
    return session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, stock, "
            "description, origin_country, supply_date, is_published) "
            "VALUES (:seller_id, :product_id, :seller_name, :price, :unit, :stock, "
            "'Своё описание', 'Россия', '2026-08-01', :is_published)"
        ),
        {
            "seller_id": seller_id,
            "product_id": product_id,
            "seller_name": seller_name,
            "price": price,
            "unit": unit,
            "stock": stock,
            "is_published": is_published,
        },
    ).lastrowid


def visible_offer(session, *, seller_id: int, seller_name: str, catalog_name: str, **kwargs) -> int:
    group_id = insert_group(session, name=f"Группа {catalog_name}")
    product_id = insert_product(session, group_id=group_id, name=catalog_name)
    return insert_offer(session, seller_id=seller_id, product_id=product_id, seller_name=seller_name, **kwargs)


def get_products(committing_session, seller_id: int, query: str = ""):
    override_session(committing_session)
    client = TestClient(app)
    try:
        return client.get(f"/api/v1/catalog/sellers/{seller_id}/products{query}")
    finally:
        app.dependency_overrides.clear()


def test_returns_both_names_of_the_offer(committing_session):
    """Собственное наименование продавца и эталонное имя позиции — оба сразу:
    какое показывать, решает интерфейс."""
    seller_id = insert_seller(committing_session, name="Пасека Ромашково")
    offer_id = visible_offer(
        committing_session,
        seller_id=seller_id,
        seller_name="Мёд гречишный, урожай 2026",
        catalog_name="Мёд",
    )

    response = get_products(committing_session, seller_id)

    assert response.status_code == 200
    body = response.json()
    assert [p["seller_product_id"] for p in body["products"]] == [offer_id]
    product = body["products"][0]
    assert product["name"] == "Мёд гречишный, урожай 2026"
    assert product["catalog_name"] == "Мёд"
    assert product["group_name"] == "Группа Мёд"
    assert (product["price"], product["unit"], product["stock"]) == ("100.00", "кг", "5.000")
    assert product["description"] == "Своё описание"
    assert (product["origin_country"], product["supply_date"]) == ("Россия", "2026-08-01")
    assert (body["page"], body["limit"], body["total"]) == (1, 20, 1)


def test_hides_unmoderated_offer(committing_session):
    """Непромодерированная строка покупателю не существует: у неё нет ни
    эталонного имени, ни товарной группы."""
    seller_id = insert_seller(committing_session, name="Продавец с новинкой")
    insert_offer(
        committing_session,
        seller_id=seller_id,
        product_id=None,
        seller_name="Ещё не разобранный товар",
    )

    response = get_products(committing_session, seller_id)

    assert response.json()["products"] == []


def test_hides_unpublished_offer(committing_session):
    """Товар без фотографии сохраняется продавцу, но покупателю не показывается
    (Publication_Model.md, «Видимость предложения в Buyer Catalog»)."""
    seller_id = insert_seller(committing_session, name="Продавец без фото")
    visible_offer(
        committing_session,
        seller_id=seller_id,
        seller_name="Товар без фото",
        catalog_name="Огурец",
        is_published=False,
    )

    response = get_products(committing_session, seller_id)

    assert response.json()["products"] == []


def test_hides_offer_of_deactivated_catalog_position(committing_session):
    """Позиция, снятая из справочника, исчезает из общего каталога — в каталоге
    продавца она не должна остаться видимой в обход того же правила."""
    seller_id = insert_seller(committing_session, name="Продавец снятой позиции")
    group_id = insert_group(committing_session, name="Группа снятой позиции")
    product_id = insert_product(committing_session, group_id=group_id, name="Снятая позиция")
    committing_session.execute(
        text("UPDATE Product SET is_active = FALSE WHERE id = :id"), {"id": product_id}
    )
    insert_offer(committing_session, seller_id=seller_id, product_id=product_id, seller_name="Товар снятой позиции")

    response = get_products(committing_session, seller_id)

    assert response.json()["products"] == []


def test_does_not_leak_offers_of_other_sellers(committing_session):
    mine = insert_seller(committing_session, name="Мой продавец")
    other = insert_seller(committing_session, name="Чужой продавец")
    visible_offer(committing_session, seller_id=mine, seller_name="Мой товар", catalog_name="Яблоко")
    visible_offer(committing_session, seller_id=other, seller_name="Чужой товар", catalog_name="Груша")

    response = get_products(committing_session, mine)

    assert [p["name"] for p in response.json()["products"]] == ["Мой товар"]


def test_visible_seller_without_offers_returns_empty_list(committing_session):
    """Продавец есть, показывать нечего — это 200 с пустым списком, а не 404."""
    seller_id = insert_seller(committing_session, name="Продавец без товаров")

    response = get_products(committing_session, seller_id)

    assert response.status_code == 200
    assert response.json() == {"products": [], "page": 1, "limit": 20, "total": 0}


def test_deactivated_seller_reports_404(committing_session):
    seller_id = insert_seller(committing_session, name="Выключенный продавец", is_active=False)
    visible_offer(committing_session, seller_id=seller_id, seller_name="Скрытый товар", catalog_name="Молоко")

    response = get_products(committing_session, seller_id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_missing_seller_reports_404(committing_session):
    response = get_products(committing_session, 999999)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_search_matches_sellers_own_name(committing_session):
    """Внутри каталога продавца покупатель ищет то, что видит на экране, —
    в том числе собственное наименование, которого в справочнике нет."""
    seller_id = insert_seller(committing_session, name="Продавец с поиском")
    visible_offer(
        committing_session,
        seller_id=seller_id,
        seller_name="Антоновка бабушкина",
        catalog_name="Яблоко",
    )
    visible_offer(committing_session, seller_id=seller_id, seller_name="Огурец длинный", catalog_name="Огурец")

    response = get_products(committing_session, seller_id, "?search=Антоновка")

    assert [p["name"] for p in response.json()["products"]] == ["Антоновка бабушкина"]


def test_search_matches_catalog_name(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с эталонным поиском")
    visible_offer(
        committing_session,
        seller_id=seller_id,
        seller_name="Антоновка бабушкина",
        catalog_name="Яблоко",
    )
    visible_offer(committing_session, seller_id=seller_id, seller_name="Огурец длинный", catalog_name="Огурец")

    response = get_products(committing_session, seller_id, "?search=Яблоко")

    assert [p["name"] for p in response.json()["products"]] == ["Антоновка бабушкина"]


def test_filters_by_group(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с группами")
    fruit_group = insert_group(committing_session, name="Фрукты")
    vegetable_group = insert_group(committing_session, name="Овощи")
    apple = insert_product(committing_session, group_id=fruit_group, name="Яблоко группы")
    cucumber = insert_product(committing_session, group_id=vegetable_group, name="Огурец группы")
    insert_offer(committing_session, seller_id=seller_id, product_id=apple, seller_name="Яблоко продавца")
    insert_offer(committing_session, seller_id=seller_id, product_id=cucumber, seller_name="Огурец продавца")

    response = get_products(committing_session, seller_id, f"?group_id={vegetable_group}")

    products = response.json()["products"]
    assert [p["name"] for p in products] == ["Огурец продавца"]
    assert (products[0]["group_id"], products[0]["group_name"]) == (vegetable_group, "Овощи")


def test_sorts_by_price(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с ценами")
    visible_offer(
        committing_session, seller_id=seller_id, seller_name="Дорогой товар", catalog_name="Дорогое", price="300.00"
    )
    visible_offer(
        committing_session, seller_id=seller_id, seller_name="Дешёвый товар", catalog_name="Дешёвое", price="50.00"
    )

    response = get_products(committing_session, seller_id, "?sort=price")

    assert [p["name"] for p in response.json()["products"]] == ["Дешёвый товар", "Дорогой товар"]


def test_sorts_by_sellers_own_name_by_default(committing_session):
    """Порядок по умолчанию — по тому полю, что показывается основным."""
    seller_id = insert_seller(committing_session, name="Продавец с алфавитом")
    visible_offer(committing_session, seller_id=seller_id, seller_name="Яблоко своё", catalog_name="Абрикос")
    visible_offer(committing_session, seller_id=seller_id, seller_name="Абрикос свой", catalog_name="Яблоко")

    response = get_products(committing_session, seller_id)

    assert [p["name"] for p in response.json()["products"]] == ["Абрикос свой", "Яблоко своё"]


def test_paginates(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с пагинацией")
    for index in range(3):
        visible_offer(
            committing_session,
            seller_id=seller_id,
            seller_name=f"Товар {index}",
            catalog_name=f"Позиция {index}",
        )

    response = get_products(committing_session, seller_id, "?page=2&limit=2")

    body = response.json()
    assert [p["name"] for p in body["products"]] == ["Товар 2"]
    assert (body["page"], body["limit"], body["total"]) == (2, 2, 3)


def test_returns_photo_urls(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с фото")
    offer_id = visible_offer(
        committing_session, seller_id=seller_id, seller_name="Товар с фото", catalog_name="Фотогеничное"
    )
    photo_id = committing_session.execute(
        text("INSERT INTO Photo (s3_key, seller_id) VALUES ('greenmarket/seller-products/test.jpg', :seller_id)"),
        {"seller_id": seller_id},
    ).lastrowid
    committing_session.execute(
        text(
            "INSERT INTO SellerProductPhoto (seller_product_id, photo_id, sort_order) "
            "VALUES (:offer_id, :photo_id, 0)"
        ),
        {"offer_id": offer_id, "photo_id": photo_id},
    )

    response = get_products(committing_session, seller_id)

    photos = response.json()["products"][0]["photos"]
    assert len(photos) == 1
    assert photos[0].endswith("greenmarket/seller-products/test.jpg")

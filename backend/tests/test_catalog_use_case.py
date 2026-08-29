from datetime import date

from sqlalchemy import text

from app.application.catalog_use_case import CatalogUseCase
from app.core.config import settings
from app.platform.photo_storage import build_photo_url


def insert_product_group(session, *, name: str, parent_id: int | None = None) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name, parent_id) VALUES (:name, :parent_id)"),
        {"name": name, "parent_id": parent_id},
    ).lastrowid


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
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, is_published) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец', :price, 'шт', TRUE)"
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

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_a])

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

    items, _ = CatalogUseCase(session).list_products(sort="price", group_ids=[group_id])

    assert [i["id"] for i in items] == [cheap_id, expensive_id]


def test_list_products_paginates(session):
    group_id = insert_product_group(session, name="Группа для пагинации")
    seller_id = insert_active_seller(session, name="Продавец для пагинации")
    product_ids = []
    for i in range(3):
        pid = insert_product(session, group_id=group_id, name=f"Товар пагинации {i}")
        insert_seller_product(session, seller_id=seller_id, product_id=pid, price=10)
        product_ids.append(pid)

    page_1, total = CatalogUseCase(session).list_products(group_ids=[group_id], page=1, limit=2)
    page_2, _ = CatalogUseCase(session).list_products(group_ids=[group_id], page=2, limit=2)

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


def test_get_product_returns_platform_seller_name_not_offer_title(session):
    group_id = insert_product_group(session, name="Группа для имени продавца")
    product_id = insert_product(session, group_id=group_id, name="Товар для имени продавца")
    seller_id = insert_active_seller(session, name="Ферма Ромашково")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    result = CatalogUseCase(session).get_product(product_id)

    assert [offer["seller_name"] for offer in result["offers"]] == ["Ферма Ромашково"]


def test_get_product_returns_product_group(session):
    group_id = insert_product_group(session, name="Группа в карточке товара")
    product_id = insert_product(session, group_id=group_id, name="Товар с товарной группой")
    seller_id = insert_active_seller(session, name="Продавец для товарной группы")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    result = CatalogUseCase(session).get_product(product_id)

    assert result["group_id"] == group_id
    assert result["group_name"] == "Группа в карточке товара"


def test_get_product_returns_origin_country_and_supply_date(session):
    group_id = insert_product_group(session, name="Группа со страной происхождения")
    product_id = insert_product(session, group_id=group_id, name="Товар со страной происхождения")
    seller_id = insert_active_seller(session, name="Продавец со страной происхождения")
    offer_id = insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)
    session.execute(
        text("UPDATE SellerProduct SET origin_country = 'Марокко', supply_date = '2026-08-01' WHERE id = :id"),
        {"id": offer_id},
    )

    offer = CatalogUseCase(session).get_product(product_id)["offers"][0]

    assert offer["origin_country"] == "Марокко"
    assert offer["supply_date"] == date(2026, 8, 1)


def test_get_product_returns_none_for_offer_without_origin_data(session):
    """Товар продавца, работающего на старой книге, — оба поля пусты, и это
    штатное состояние, а не отсутствие данных."""
    group_id = insert_product_group(session, name="Группа без страны происхождения")
    product_id = insert_product(session, group_id=group_id, name="Товар без страны происхождения")
    seller_id = insert_active_seller(session, name="Продавец без страны происхождения")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    offer = CatalogUseCase(session).get_product(product_id)["offers"][0]

    assert offer["origin_country"] is None
    assert offer["supply_date"] is None


def test_get_product_returns_none_for_product_without_visible_offers(session):
    group_id = insert_product_group(session, name="Группа для get_product без предложений")
    product_id = insert_product(session, group_id=group_id, name="Товар без предложений get_product")

    assert CatalogUseCase(session).get_product(product_id) is None


def test_get_product_returns_none_for_missing_product(session):
    assert CatalogUseCase(session).get_product(999_999) is None


def test_get_product_breaks_price_ties_deterministically_by_offer_id(session):
    group_id = insert_product_group(session, name="Группа для tie-break")
    product_id = insert_product(session, group_id=group_id, name="Товар с одинаковой ценой")
    seller_a = insert_active_seller(session, name="Продавец A для tie-break")
    seller_b = insert_active_seller(session, name="Продавец B для tie-break")
    offer_a = insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=30)
    offer_b = insert_seller_product(session, seller_id=seller_b, product_id=product_id, price=30)
    lower_id, higher_id = sorted([offer_a, offer_b])

    result = CatalogUseCase(session).get_product(product_id)

    assert [offer["seller_product_id"] for offer in result["offers"]] == [lower_id, higher_id]


def test_list_products_breaks_price_ties_deterministically_for_cheapest_offer(session):
    group_id = insert_product_group(session, name="Группа для list_products tie-break")
    product_id = insert_product(session, group_id=group_id, name="Товар для list_products tie-break")
    seller_a = insert_active_seller(session, name="Продавец A для list_products tie-break")
    seller_b = insert_active_seller(session, name="Продавец B для list_products tie-break")
    offer_a = insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=30)
    offer_b = insert_seller_product(session, seller_id=seller_b, product_id=product_id, price=30)
    lower_id, higher_id = sorted([offer_a, offer_b])
    # attach a photo to each offer so the winning tie-break is observable
    # through the public contract (which photo shows on the tile), not by
    # peeking at internal state.
    insert_seller_product_photo(session, seller_product_id=lower_id, s3_key="lower.jpg")
    insert_seller_product_photo(session, seller_product_id=higher_id, s3_key="higher.jpg")

    items, _ = CatalogUseCase(session).list_products(group_ids=[group_id])

    item = next(i for i in items if i["id"] == product_id)
    assert item["min_price"] == 30
    assert item["photos"] == [
        build_photo_url(
            "lower.jpg", bucket=settings.s3_bucket, region=settings.s3_region, public_base_url=settings.s3_public_base_url
        )
    ]


def insert_seller_product_photo(session, *, seller_product_id: int, s3_key: str) -> int:
    photo_id = session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid
    session.execute(
        text("INSERT INTO SellerProductPhoto (seller_product_id, photo_id) VALUES (:seller_product_id, :photo_id)"),
        {"seller_product_id": seller_product_id, "photo_id": photo_id},
    )
    return photo_id


def test_get_product_returns_photo_urls_for_offer(session):
    group_id = insert_product_group(session, name="Группа для get_product фото")
    product_id = insert_product(session, group_id=group_id, name="Товар для get_product фото")
    seller_id = insert_active_seller(session, name="Продавец для get_product фото")
    offer_id = insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=15)
    insert_seller_product_photo(session, seller_product_id=offer_id, s3_key="offer.jpg")

    result = CatalogUseCase(session).get_product(product_id)

    expected_url = build_photo_url(
        "offer.jpg", bucket=settings.s3_bucket, region=settings.s3_region, public_base_url=settings.s3_public_base_url
    )
    assert result["offers"][0]["photos"] == [expected_url]


def test_list_products_accepts_several_groups_at_once(session):
    """Несколько категорий сразу — объединение (OR), а не пересечение: товар
    относится ровно к одной группе, и пересечение всегда было бы пустым."""
    group_a = insert_product_group(session, name="Группа A мульти-фильтра")
    group_b = insert_product_group(session, name="Группа B мульти-фильтра")
    group_c = insert_product_group(session, name="Группа C мульти-фильтра")
    product_a = insert_product(session, group_id=group_a, name="Товар группы A мульти")
    product_b = insert_product(session, group_id=group_b, name="Товар группы B мульти")
    product_c = insert_product(session, group_id=group_c, name="Товар группы C мульти")
    seller_id = insert_active_seller(session, name="Продавец мульти-фильтра")
    for product_id in (product_a, product_b, product_c):
        insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    items, total = CatalogUseCase(session).list_products(group_ids=[group_a, group_b])

    ids = [i["id"] for i in items]
    assert product_a in ids
    assert product_b in ids
    assert product_c not in ids
    assert total == 2


def test_list_products_by_parent_group_includes_child_products(session):
    parent = insert_product_group(session, name="Родитель для фильтра по ветке")
    child = insert_product_group(session, name="Ребёнок для фильтра по ветке", parent_id=parent)
    own_product = insert_product(session, group_id=parent, name="Товар прямо в родительской группе")
    child_product = insert_product(session, group_id=child, name="Товар дочерней группы")
    seller_id = insert_active_seller(session, name="Продавец фильтра по ветке")
    insert_seller_product(session, seller_id=seller_id, product_id=own_product, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=child_product, price=10)

    items, total = CatalogUseCase(session).list_products(group_ids=[parent])

    ids = [i["id"] for i in items]
    assert own_product in ids
    assert child_product in ids
    assert total == 2


def test_list_products_multi_group_keeps_search_and_pagination(session):
    """Мульти-категория считается вместе с остальными фильтрами, а `total` —
    после всех: иначе пагинация на фронте разъедется с содержимым страницы."""
    group_a = insert_product_group(session, name="Группа A мульти+поиск")
    group_b = insert_product_group(session, name="Группа B мульти+поиск")
    matching_a = insert_product(session, group_id=group_a, name="Редис Дайкон мультипоиск")
    matching_b = insert_product(session, group_id=group_b, name="Редис Красный мультипоиск")
    other = insert_product(session, group_id=group_a, name="Пастернак мультипоиск")
    seller_id = insert_active_seller(session, name="Продавец мульти+поиск")
    for product_id in (matching_a, matching_b, other):
        insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    page_1, total = CatalogUseCase(session).list_products(
        group_ids=[group_a, group_b], search="мультипоиск", page=1, limit=2
    )

    assert total == 3
    assert len(page_1) == 2


def test_list_groups_counts_products_of_the_whole_branch(session):
    """`product_count` считается по той же границе, по которой работает фильтр:
    иначе категория обещала бы «Овощи (1)», а по клику отдавала бы четыре."""
    parent = insert_product_group(session, name="Родитель для счётчика ветки")
    child = insert_product_group(session, name="Ребёнок для счётчика ветки", parent_id=parent)
    own_product = insert_product(session, group_id=parent, name="Товар родителя для счётчика")
    child_product = insert_product(session, group_id=child, name="Товар ребёнка для счётчика")
    seller_id = insert_active_seller(session, name="Продавец счётчика ветки")
    insert_seller_product(session, seller_id=seller_id, product_id=own_product, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=child_product, price=10)

    groups = {g["id"]: g for g in CatalogUseCase(session).list_groups()}

    assert groups[parent]["product_count"] == 2
    assert groups[child]["product_count"] == 1


def test_suggest_returns_only_names_of_visible_products(session):
    group_id = insert_product_group(session, name="Группа подсказок: видимость")
    visible = insert_product(session, group_id=group_id, name="Клюква вяленая, подсказка видимая")
    insert_product(session, group_id=group_id, name="Клюква мочёная, подсказка без предложений")
    seller_id = insert_active_seller(session, name="Продавец подсказок: видимость")
    insert_seller_product(session, seller_id=seller_id, product_id=visible, price=10)

    names = CatalogUseCase(session).suggest_names(q="клюква", group_ids=[group_id])

    assert names == ["Клюква вяленая, подсказка видимая"]


def test_suggest_excludes_names_of_inactive_sellers(session):
    group_id = insert_product_group(session, name="Группа подсказок: неактивный продавец")
    product_id = insert_product(session, group_id=group_id, name="Морковь, подсказка неактивного продавца")
    seller_id = insert_active_seller(session, name="Продавец подсказок: скоро неактивен")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    names = CatalogUseCase(session).suggest_names(group_ids=[group_id])

    assert names == []


def test_suggest_returns_name_once_for_several_offers(session):
    """Единица подсказки — наименование справочника, а не строка каталога.

    Повторная публикация книги заводит новые предложения на ту же позицию, и у
    разных продавцов позиция та же самая: в подсказках всё это обязано слиться
    в одно наименование, иначе покупатель увидит список из одного слова.
    """
    group_id = insert_product_group(session, name="Группа подсказок: дубли")
    product_id = insert_product(session, group_id=group_id, name="Мёд гречишный, подсказка одна")
    seller_a = insert_active_seller(session, name="Продавец подсказок: дубли А")
    seller_b = insert_active_seller(session, name="Продавец подсказок: дубли Б")
    insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=10)
    insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=20)
    insert_seller_product(session, seller_id=seller_b, product_id=product_id, price=30)

    names = CatalogUseCase(session).suggest_names(group_ids=[group_id])

    assert names == ["Мёд гречишный, подсказка одна"]


def test_suggest_filters_by_seller(session):
    group_id = insert_product_group(session, name="Группа подсказок: продавец")
    own = insert_product(session, group_id=group_id, name="Свёкла, подсказка своего продавца")
    other = insert_product(session, group_id=group_id, name="Тыква, подсказка чужого продавца")
    seller_a = insert_active_seller(session, name="Продавец подсказок: свой")
    seller_b = insert_active_seller(session, name="Продавец подсказок: чужой")
    insert_seller_product(session, seller_id=seller_a, product_id=own, price=10)
    insert_seller_product(session, seller_id=seller_b, product_id=other, price=10)

    names = CatalogUseCase(session).suggest_names(group_ids=[group_id], seller_id=seller_a)

    assert names == ["Свёкла, подсказка своего продавца"]


def test_suggest_matches_words_in_any_order(session):
    group_id = insert_product_group(session, name="Группа подсказок: порядок слов")
    product_id = insert_product(session, group_id=group_id, name="Клюква вяленая, подсказка порядок")
    seller_id = insert_active_seller(session, name="Продавец подсказок: порядок слов")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    names = CatalogUseCase(session).suggest_names(q="вяленая клюква", group_ids=[group_id])

    assert names == ["Клюква вяленая, подсказка порядок"]


def test_suggest_treats_percent_as_plain_character(session):
    """`%` в запросе не должен возвращать каталог целиком — та же причина, по
    которой он экранирован в `search`, и для голосового ввода она острее:
    спецсимвол там появляется не от покупателя, а от распознавания речи."""
    group_id = insert_product_group(session, name="Группа подсказок: процент")
    product_id = insert_product(session, group_id=group_id, name="Огурцы, подсказка без процента")
    seller_id = insert_active_seller(session, name="Продавец подсказок: процент")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    assert CatalogUseCase(session).suggest_names(q="%", group_ids=[group_id]) == []


def test_suggest_without_query_returns_alphabetical_head(session):
    group_id = insert_product_group(session, name="Группа подсказок: лимит")
    seller_id = insert_active_seller(session, name="Продавец подсказок: лимит")
    for name in ("Ямс, подсказка лимит", "Абрикос, подсказка лимит", "Базилик, подсказка лимит"):
        product_id = insert_product(session, group_id=group_id, name=name)
        insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)

    names = CatalogUseCase(session).suggest_names(q="   ", group_ids=[group_id], limit=2)

    assert names == ["Абрикос, подсказка лимит", "Базилик, подсказка лимит"]

"""Правка каталога продавцом: создание позиции и частичное изменение.

Модерация здесь не решение, а следствие: статус выводится из выбранной
товарной позиции, и продавец не может назначить его сам.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.application.seller_catalog_use_case import (
    DuplicateSellerSkuError,
    ProductNotSelectableError,
    SellerCatalogUseCase,
    SellerProductNotFoundError,
)
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:u)"), {"u": user_id}).lastrowid


def insert_group(session, *, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO ProductGroup (name, is_active) VALUES (:n, :a)"),
        {"n": f"{name} {uuid.uuid4().hex[:6]}", "a": is_active},
    ).lastrowid


def insert_product(session, *, group_id: int, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name, is_active) VALUES (:g, :n, :a)"),
        {"g": group_id, "n": f"{name} {uuid.uuid4().hex[:6]}", "a": is_active},
    ).lastrowid


def use_case(session) -> SellerCatalogUseCase:
    return SellerCatalogUseCase(session)


def base_fields(**overrides):
    fields = {
        "seller_name": "Товар продавца",
        "price": 250,
        "stock": 12,
        "unit": "кг",
        "product_id": None,
        "description": None,
        "origin_country": None,
        "supply_date": None,
        "seller_sku": None,
    }
    fields.update(overrides)
    return fields


def test_create_without_product_waits_for_moderation_and_stays_hidden(session):
    seller_id = insert_seller(session, name="Ферма создания без позиции")

    created = use_case(session).create(seller_id, base_fields())

    assert created.moderation_status == "WAIT_PRODUCT"
    assert created.is_published is False


def test_create_with_active_product_is_resolved(session):
    seller_id = insert_seller(session, name="Ферма создания с позицией")
    group_id = insert_group(session, name="Группа создания")
    product_id = insert_product(session, group_id=group_id, name="Позиция создания")

    created = use_case(session).create(seller_id, base_fields(product_id=product_id))

    assert created.product_id == product_id
    assert created.moderation_status == "RESOLVED"
    # Даже сопоставленный товар не появляется на витрине сам: публикация —
    # отдельная операция.
    assert created.is_published is False


def test_create_with_inactive_product_is_rejected(session):
    """Привязка к снятой позиции выглядела бы как завершённая модерация, но
    покупателю товар всё равно не показался бы."""
    seller_id = insert_seller(session, name="Ферма снятой позиции")
    group_id = insert_group(session, name="Группа снятой позиции")
    product_id = insert_product(session, group_id=group_id, name="Снятая позиция", is_active=False)

    with pytest.raises(ProductNotSelectableError):
        use_case(session).create(seller_id, base_fields(product_id=product_id))


def test_create_with_unknown_product_is_rejected(session):
    seller_id = insert_seller(session, name="Ферма неизвестной позиции")

    with pytest.raises(ProductNotSelectableError):
        use_case(session).create(seller_id, base_fields(product_id=999_999))


def test_create_with_duplicate_sku_is_rejected(session):
    """Артикул — ключ сопоставления при публикации из книги, и дублей у одного
    продавца база не допускает (миграция 018)."""
    seller_id = insert_seller(session, name="Ферма дублей артикула")
    sku = f"SKU-{uuid.uuid4().hex[:8]}"
    use_case(session).create(seller_id, base_fields(seller_sku=sku))

    with pytest.raises(DuplicateSellerSkuError):
        use_case(session).create(seller_id, base_fields(seller_sku=sku))


def test_update_changes_only_given_fields(session):
    seller_id = insert_seller(session, name="Ферма частичной правки")
    created = use_case(session).create(seller_id, base_fields(description="Исходное описание"))

    updated = use_case(session).update(seller_id, created.id, {"price": 999})

    assert float(updated.price) == 999
    assert updated.description == "Исходное описание"
    assert updated.seller_name == "Товар продавца"


def test_update_clears_nullable_field_when_null_given(session):
    seller_id = insert_seller(session, name="Ферма очистки поля")
    created = use_case(session).create(seller_id, base_fields(origin_country="Армения"))

    updated = use_case(session).update(seller_id, created.id, {"origin_country": None})

    assert updated.origin_country is None


def test_update_to_another_product_resets_moderator_decision(session):
    """Смена товарной позиции: прежнее решение модератора относилось к другой
    позиции и больше не действует."""
    seller_id = insert_seller(session, name="Ферма смены позиции")
    moderator_id = insert_user(session, name="Модератор смены позиции")
    group_id = insert_group(session, name="Группа смены позиции")
    first = insert_product(session, group_id=group_id, name="Первая позиция")
    second = insert_product(session, group_id=group_id, name="Вторая позиция")
    created = use_case(session).create(seller_id, base_fields(product_id=first))
    created.moderator_id = moderator_id
    created.moderated_at = date.today()
    created.moderation_comment = "Проверено"
    session.flush()

    updated = use_case(session).update(seller_id, created.id, {"product_id": second})

    assert updated.product_id == second
    assert updated.moderation_status == "RESOLVED"
    assert updated.moderator_id is None
    assert updated.moderated_at is None
    assert updated.moderation_comment is None


def test_update_to_null_product_returns_to_moderation_queue(session):
    seller_id = insert_seller(session, name="Ферма возврата в очередь")
    group_id = insert_group(session, name="Группа возврата")
    product_id = insert_product(session, group_id=group_id, name="Позиция возврата")
    created = use_case(session).create(seller_id, base_fields(product_id=product_id))

    updated = use_case(session).update(seller_id, created.id, {"product_id": None})

    assert updated.product_id is None
    assert updated.moderation_status == "WAIT_PRODUCT"


def test_update_to_inactive_product_is_rejected(session):
    seller_id = insert_seller(session, name="Ферма правки на снятую")
    group_id = insert_group(session, name="Группа правки на снятую")
    inactive = insert_product(session, group_id=group_id, name="Снятая позиция правки", is_active=False)
    created = use_case(session).create(seller_id, base_fields())

    with pytest.raises(ProductNotSelectableError):
        use_case(session).update(seller_id, created.id, {"product_id": inactive})


def test_update_of_foreign_product_is_not_found(session):
    mine = insert_seller(session, name="Ферма своя правка")
    theirs = insert_seller(session, name="Ферма чужая правка")
    foreign = use_case(session).create(theirs, base_fields())

    with pytest.raises(SellerProductNotFoundError):
        use_case(session).update(mine, foreign.id, {"price": 1})


def test_update_never_touches_visibility(session):
    """is_published меняет только публикация — PATCH к витрине отношения не имеет."""
    seller_id = insert_seller(session, name="Ферма витрины при правке")
    created = use_case(session).create(seller_id, base_fields())
    created.is_published = True
    session.flush()

    updated = use_case(session).update(seller_id, created.id, {"price": 5})

    assert updated.is_published is True


def test_update_to_duplicate_sku_is_rejected(session):
    seller_id = insert_seller(session, name="Ферма дубля при правке")
    taken = f"SKU-{uuid.uuid4().hex[:8]}"
    use_case(session).create(seller_id, base_fields(seller_sku=taken))
    other = use_case(session).create(seller_id, base_fields(seller_sku=f"SKU-{uuid.uuid4().hex[:8]}"))

    with pytest.raises(DuplicateSellerSkuError):
        use_case(session).update(seller_id, other.id, {"seller_sku": taken})


def test_update_bumps_updated_at(session):
    seller_id = insert_seller(session, name="Ферма метки времени")
    created = use_case(session).create(seller_id, base_fields())
    before = created.updated_at

    updated = use_case(session).update(seller_id, created.id, {"stock": 3})

    assert updated.updated_at >= before


def test_created_row_belongs_to_its_seller_only(session):
    seller_id = insert_seller(session, name="Ферма принадлежности")
    created = use_case(session).create(seller_id, base_fields())

    found = SellerProductRepository(session).find_for_seller_admin(seller_id, created.id)

    assert found is not None


# ── Оптимистическая блокировка и идемпотентность ─────────────────────────────


def test_version_starts_at_one_and_grows_on_change(session):
    seller_id = insert_seller(session, name="Ферма версии строки")
    created = use_case(session).create(seller_id, base_fields())
    assert created.version == 1

    updated = use_case(session).update(seller_id, created.id, {"price": 500})

    assert updated.version == 2


def test_version_does_not_grow_when_nothing_actually_changed(session):
    """Повторная отправка тех же значений не должна ронять чужие решения:
    версия — это ревизия содержимого, а не счётчик запросов."""
    seller_id = insert_seller(session, name="Ферма неизменной версии")
    created = use_case(session).create(seller_id, base_fields(price=250))

    updated = use_case(session).update(seller_id, created.id, {"price": 250})

    assert updated.version == 1


def test_update_with_stale_expected_version_is_rejected(session):
    """Чужое изменение между чтением и записью не должно быть затёрто."""
    from app.application.seller_catalog_use_case import CatalogChangedError

    seller_id = insert_seller(session, name="Ферма устаревшей версии")
    created = use_case(session).create(seller_id, base_fields())
    use_case(session).update(seller_id, created.id, {"price": 300})  # кто-то другой

    with pytest.raises(CatalogChangedError):
        use_case(session).update(seller_id, created.id, {"price": 400}, expected_version=1)


def test_update_with_current_expected_version_succeeds(session):
    seller_id = insert_seller(session, name="Ферма актуальной версии")
    created = use_case(session).create(seller_id, base_fields())

    updated = use_case(session).update(seller_id, created.id, {"price": 400}, expected_version=1)

    assert float(updated.price) == 400
    assert updated.version == 2


def test_update_without_expected_version_still_works(session):
    """Прежний контракт сохраняется: без токена действует last-write-wins,
    как было зафиксировано в ТЗ Seller Catalog API."""
    seller_id = insert_seller(session, name="Ферма без токена версии")
    created = use_case(session).create(seller_id, base_fields())

    updated = use_case(session).update(seller_id, created.id, {"price": 400})

    assert float(updated.price) == 400


def test_create_with_same_idempotency_key_returns_the_first_row(session):
    """Потеря ответа после успешного создания не должна плодить дубли."""
    seller_id = insert_seller(session, name="Ферма идемпотентного создания")
    key = str(uuid.uuid4())

    first = use_case(session).create(seller_id, base_fields(), idempotency_key=key)
    second = use_case(session).create(seller_id, base_fields(seller_name="Другое имя"), idempotency_key=key)

    assert second.id == first.id
    # Повтор — это та же логическая операция, а не правка: значения первой
    # попытки остаются, второе тело не применяется.
    assert second.seller_name == "Товар продавца"


def test_same_idempotency_key_of_another_seller_creates_its_own_row(session):
    """Ключ генерирует клиент в своей книге — совпадение у двух продавцов их
    частное дело, а не конфликт."""
    first_seller = insert_seller(session, name="Ферма ключа первая")
    second_seller = insert_seller(session, name="Ферма ключа вторая")
    key = str(uuid.uuid4())

    one = use_case(session).create(first_seller, base_fields(), idempotency_key=key)
    two = use_case(session).create(second_seller, base_fields(), idempotency_key=key)

    assert one.id != two.id


def test_create_without_idempotency_key_is_not_deduplicated(session):
    seller_id = insert_seller(session, name="Ферма без ключа идемпотентности")

    first = use_case(session).create(seller_id, base_fields())
    second = use_case(session).create(seller_id, base_fields())

    assert first.id != second.id

from sqlalchemy import text

from app.infrastructure.repositories.product_repository import ProductRepository


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, group_id: int, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name, is_active) VALUES (:group_id, :name, :is_active)"),
        {"group_id": group_id, "name": name, "is_active": is_active},
    ).lastrowid


def test_find_by_id_returns_seeded_product(session):
    """Интеграционный тест на реальной базе — без mock, как в ТЗ PR-002.

    Ищем товар по имени (без захардкоженных id, см. database/seeders/002_products.sql),
    затем проверяем find_by_id() тем же id.
    """
    repo = ProductRepository(session)

    orange = repo.find_by_name("Апельсин")
    assert orange is not None

    found = repo.find_by_id(orange.id)
    assert found is not None
    assert found.id == orange.id
    assert found.name == "Апельсин"


def test_find_by_id_returns_none_for_missing_product(session):
    repo = ProductRepository(session)
    assert repo.find_by_id(999_999) is None


def test_list_active_excludes_inactive_products(session):
    group_id = insert_product_group(session, name="Группа для list_active")
    active_id = insert_product(session, group_id=group_id, name="Активный товар list_active")
    insert_product(session, group_id=group_id, name="Неактивный товар list_active", is_active=False)

    result = ProductRepository(session).list_active()

    ids = [p.id for p in result]
    assert active_id in ids
    assert all(p.is_active for p in result)


def test_list_active_filters_by_group_id(session):
    group_a = insert_product_group(session, name="Группа A для фильтра")
    group_b = insert_product_group(session, name="Группа B для фильтра")
    product_a = insert_product(session, group_id=group_a, name="Товар группы A")
    insert_product(session, group_id=group_b, name="Товар группы B")

    result = ProductRepository(session).list_active(group_id=group_a)

    assert [p.id for p in result] == [product_a]


def test_list_active_filters_by_search_case_insensitive(session):
    # Названия ниже намеренно не пересекаются с database/seeders/002_products.sql
    # (там уже есть активный товар "Яблоко") — иначе поиск подхватит и его.
    group_id = insert_product_group(session, name="Группа для поиска")
    kiwi_id = insert_product(session, group_id=group_id, name="Киви Хейворд")
    insert_product(session, group_id=group_id, name="Манго Кенийское")

    result = ProductRepository(session).list_active(search="киви")

    assert [p.id for p in result] == [kiwi_id]


def test_get_active_returns_none_for_inactive_product(session):
    group_id = insert_product_group(session, name="Группа для get_active")
    inactive_id = insert_product(session, group_id=group_id, name="Неактивный товар get_active", is_active=False)

    assert ProductRepository(session).get_active(inactive_id) is None


def test_get_active_returns_product_for_active_product(session):
    group_id = insert_product_group(session, name="Группа для get_active 2")
    active_id = insert_product(session, group_id=group_id, name="Активный товар get_active")

    result = ProductRepository(session).get_active(active_id)

    assert result is not None
    assert result.id == active_id

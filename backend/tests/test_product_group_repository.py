from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository


def insert_product_group(session, *, name: str, parent_id: int | None = None, is_active: bool = True, sort_order: int = 0) -> int:
    return session.execute(
        text(
            "INSERT INTO ProductGroup (name, parent_id, is_active, sort_order) "
            "VALUES (:name, :parent_id, :is_active, :sort_order)"
        ),
        {"name": name, "parent_id": parent_id, "is_active": is_active, "sort_order": sort_order},
    ).lastrowid


def test_list_active_excludes_inactive_groups(session):
    active_id = insert_product_group(session, name="Активная группа для list_active")
    insert_product_group(session, name="Неактивная группа для list_active", is_active=False)

    result = ProductGroupRepository(session).list_active()

    ids = [g.id for g in result]
    assert active_id in ids
    assert all(g.is_active for g in result)


def test_list_active_orders_by_sort_order_then_name(session):
    insert_product_group(session, name="Z-группа sort_order test", sort_order=1)
    insert_product_group(session, name="A-группа sort_order test", sort_order=1)
    first_id = insert_product_group(session, name="Группа с sort_order 0", sort_order=0)

    result = ProductGroupRepository(session).list_active()

    assert result[0].id == first_id

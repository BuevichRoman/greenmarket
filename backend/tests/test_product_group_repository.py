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
    # Порядок проверяется только между группами этого теста: в БД разработчика
    # лежат и сиды, и группы реальных продавцов — среди них есть свои группы с
    # sort_order 0, и абсолютная позиция в списке ничего не значила бы.
    last_id = insert_product_group(session, name="Z-группа sort_order test", sort_order=1)
    middle_id = insert_product_group(session, name="A-группа sort_order test", sort_order=1)
    first_id = insert_product_group(session, name="Группа с sort_order 0 test", sort_order=0)

    result = ProductGroupRepository(session).list_active()

    own_order = [g.id for g in result if g.id in {first_id, middle_id, last_id}]
    assert own_order == [first_id, middle_id, last_id]


def test_expand_subtrees_adds_all_descendants(session):
    """Выбор родительской группы означает всю её ветку: в справочнике товары
    висят и на листьях, и на корнях (`Лук` — прямо в «Овощах»), поэтому точное
    совпадение оставило бы покупателя без большей части категории."""
    root = insert_product_group(session, name="Корень для expand_subtrees")
    child = insert_product_group(session, name="Ребёнок для expand_subtrees", parent_id=root)
    grandchild = insert_product_group(session, name="Внук для expand_subtrees", parent_id=child)
    outside = insert_product_group(session, name="Соседняя ветка expand_subtrees")

    result = ProductGroupRepository(session).expand_subtrees([root])

    assert set(result) == {root, child, grandchild}
    assert outside not in result


def test_expand_subtrees_keeps_leaf_selection_unchanged(session):
    root = insert_product_group(session, name="Корень для листа expand_subtrees")
    leaf = insert_product_group(session, name="Лист для expand_subtrees", parent_id=root)

    assert ProductGroupRepository(session).expand_subtrees([leaf]) == [leaf]


def test_expand_subtrees_merges_overlapping_branches_without_duplicates(session):
    root = insert_product_group(session, name="Корень для пересечения expand_subtrees")
    child = insert_product_group(session, name="Ребёнок для пересечения expand_subtrees", parent_id=root)

    result = ProductGroupRepository(session).expand_subtrees([root, child])

    assert sorted(result) == sorted({root, child})
    assert len(result) == len(set(result))


def test_expand_subtrees_keeps_unknown_id(session):
    """Несуществующая группа остаётся в списке: фильтр по ней просто ничего не
    найдёт. Выбросить её означало бы отдать каталог целиком — молча и не тем."""
    result = ProductGroupRepository(session).expand_subtrees([2_000_000_001])

    assert result == [2_000_000_001]


def test_expand_subtrees_on_empty_input_returns_empty(session):
    assert ProductGroupRepository(session).expand_subtrees([]) == []


def test_subtree_ids_by_group_maps_each_requested_group_to_its_branch(session):
    root = insert_product_group(session, name="Корень для subtree_ids_by_group")
    child = insert_product_group(session, name="Ребёнок для subtree_ids_by_group", parent_id=root)

    result = ProductGroupRepository(session).subtree_ids_by_group([root, child])

    assert set(result[root]) == {root, child}
    assert result[child] == [child]

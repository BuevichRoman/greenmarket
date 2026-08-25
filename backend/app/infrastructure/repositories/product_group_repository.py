from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.models import Product, ProductGroup

_MAX_TREE_DEPTH = 50


class ProductGroupRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, group_id: int) -> ProductGroup | None:
        return self.session.get(ProductGroup, group_id)

    def find_by_name(self, name: str) -> ProductGroup | None:
        return self.session.query(ProductGroup).filter(ProductGroup.name == name).first()

    def list_active(self) -> list[ProductGroup]:
        return (
            self.session.query(ProductGroup)
            .filter(ProductGroup.is_active.is_(True))
            .order_by(ProductGroup.sort_order, ProductGroup.name)
            .all()
        )

    def list_all_with_product_count(self) -> list[tuple[ProductGroup, int]]:
        """Для Admin Cabinet — включая деактивированные группы: скрытую группу
        иначе невозможно вернуть в работу."""
        product_count = (
            select(func.count(Product.id))
            .where(Product.product_group_id == ProductGroup.id)
            .scalar_subquery()
        )
        rows = (
            self.session.query(ProductGroup, product_count)
            .order_by(ProductGroup.sort_order, ProductGroup.name)
            .all()
        )
        return [(group, count) for group, count in rows]

    def count_products(self, group_id: int) -> int:
        return (
            self.session.query(func.count(Product.id))
            .filter(Product.product_group_id == group_id)
            .scalar()
        )

    def create(self, *, name: str, parent_id: int | None, sort_order: int) -> ProductGroup:
        group = ProductGroup(name=name, parent_id=parent_id, sort_order=sort_order, is_active=True)
        self.session.add(group)
        self.session.flush()
        return group

    def subtree_ids_by_group(self, group_ids: list[int]) -> dict[int, list[int]]:
        """Для каждой запрошенной группы — она сама и все её потомки.

        Выбор категории в каталоге покупателя означает ветку целиком, а не одну
        строку справочника: товары висят и на листьях, и на корнях сразу
        («Лук» лежит прямо в «Овощах»), поэтому точное совпадение оставило бы
        покупателя без большей части выбранной категории.

        Неизвестный id возвращается как есть: фильтр по нему ничего не найдёт —
        это честнее, чем выбросить его и молча отдать каталог целиком.

        Активность группы здесь не проверяется — фильтр каталога её никогда не
        проверял и для одиночной группы: видимость товара определяют
        `Product.is_active` и наличие предложения, а не флаг его группы.
        """
        if not group_ids:
            return {}

        children_by_parent: dict[int, list[int]] = {}
        for child_id, parent_id in self.session.query(ProductGroup.id, ProductGroup.parent_id):
            if parent_id is not None:
                children_by_parent.setdefault(parent_id, []).append(child_id)

        result: dict[int, list[int]] = {}
        for group_id in group_ids:
            if group_id in result:
                continue
            branch: list[int] = []
            seen: set[int] = set()
            queue = [group_id]
            while queue:
                current = queue.pop(0)
                # Множество посещённых защищает от цикла в parent_id: схема его
                # не допускает, но обход не должен зависеть от этого.
                if current in seen:
                    continue
                seen.add(current)
                branch.append(current)
                queue.extend(children_by_parent.get(current, []))
            result[group_id] = branch
        return result

    def expand_subtrees(self, group_ids: list[int]) -> list[int]:
        """Те же ветки, но одним списком без повторов — для фильтра `IN (...)`,
        где пересечение выбранных веток значения не имеет."""
        expanded: list[int] = []
        seen: set[int] = set()
        for branch in self.subtree_ids_by_group(group_ids).values():
            for group_id in branch:
                if group_id not in seen:
                    seen.add(group_id)
                    expanded.append(group_id)
        return expanded

    def is_descendant(self, group_id: int, candidate_id: int) -> bool:
        """Является ли candidate_id потомком group_id. Нужно, чтобы не дать
        перенести группу под собственного потомка: ветка осталась бы в списке,
        но ни в одну корневую не попала бы."""
        current = self.find_by_id(candidate_id)
        for _ in range(_MAX_TREE_DEPTH):
            if current is None or current.parent_id is None:
                return False
            if current.parent_id == group_id:
                return True
            current = self.find_by_id(current.parent_id)
        return False

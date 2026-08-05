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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.models import Product, ProductGroup, SellerProduct


class ProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, product_id: int) -> Product | None:
        return self.session.get(Product, product_id)

    def find_by_name(self, name: str) -> Product | None:
        return self.session.query(Product).filter(Product.name == name).first()

    def list_by_group(self, product_group_id: int) -> list[Product]:
        return (
            self.session.query(Product)
            .filter(Product.product_group_id == product_group_id)
            .all()
        )

    def list_active(self, *, group_id: int | None = None, search: str | None = None) -> list[Product]:
        query = self.session.query(Product).filter(Product.is_active.is_(True))
        if group_id is not None:
            query = query.filter(Product.product_group_id == group_id)
        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))
        return query.order_by(Product.name).all()

    def list_for_admin(
        self, *, group_id: int | None, query: str | None, page: int, limit: int
    ) -> tuple[list[tuple[Product, str, int]], int]:
        """Позиции справочника для Admin Cabinet: с названием группы и числом
        связанных предложений, включая деактивированные позиции.

        `offer_count` — не украшение: Admin_MVP.md запрещает удалять Product
        при связанных SellerProduct, и админ должен видеть это до правки.
        """
        offer_count = (
            select(func.count(SellerProduct.id))
            .where(SellerProduct.product_id == Product.id)
            .scalar_subquery()
        )
        statement = self.session.query(Product, ProductGroup.name, offer_count).join(
            ProductGroup, ProductGroup.id == Product.product_group_id
        )
        if group_id is not None:
            statement = statement.filter(Product.product_group_id == group_id)
        if query:
            statement = statement.filter(Product.name.ilike(f"%{query}%"))

        total = statement.order_by(None).count()
        rows = statement.order_by(Product.name).offset((page - 1) * limit).limit(limit).all()
        return [(product, group_name, count) for product, group_name, count in rows], total

    def count_offers(self, product_id: int) -> int:
        return (
            self.session.query(func.count(SellerProduct.id))
            .filter(SellerProduct.product_id == product_id)
            .scalar()
        )

    def create(self, *, product_group_id: int, name: str, description: str | None) -> Product:
        product = Product(
            product_group_id=product_group_id, name=name, description=description, is_active=True
        )
        self.session.add(product)
        self.session.flush()
        return product

    def get_active(self, product_id: int) -> Product | None:
        return (
            self.session.query(Product)
            .filter(Product.id == product_id, Product.is_active.is_(True))
            .first()
        )

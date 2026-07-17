from sqlalchemy.orm import Session

from app.infrastructure.models import Product


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

    def get_active(self, product_id: int) -> Product | None:
        return (
            self.session.query(Product)
            .filter(Product.id == product_id, Product.is_active.is_(True))
            .first()
        )

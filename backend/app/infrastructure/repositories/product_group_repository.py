from sqlalchemy.orm import Session

from app.infrastructure.models import ProductGroup


class ProductGroupRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, group_id: int) -> ProductGroup | None:
        return self.session.get(ProductGroup, group_id)

    def find_by_name(self, name: str) -> ProductGroup | None:
        return self.session.query(ProductGroup).filter(ProductGroup.name == name).first()

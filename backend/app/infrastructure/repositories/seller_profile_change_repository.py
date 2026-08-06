from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProfileChange


class SellerProfileChangeRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        seller_id: int,
        field: str,
        old_value: str | None,
        new_value: str | None,
        author_user_id: int,
        author_role: str,
    ) -> SellerProfileChange:
        change = SellerProfileChange(
            seller_id=seller_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            author_user_id=author_user_id,
            author_role=author_role,
        )
        self.session.add(change)
        return change

    def list_by_seller(self, seller_id: int) -> list[SellerProfileChange]:
        return (
            self.session.query(SellerProfileChange)
            .filter(SellerProfileChange.seller_id == seller_id)
            .order_by(SellerProfileChange.id.desc())
            .all()
        )

    def list_recent(self, *, limit: int) -> list[SellerProfileChange]:
        """Лента последних изменений для Admin Cabinet.

        Сортировка по `id`, а не по `created_at`: несколько полей, изменённых
        одним PUT, получают одинаковую метку времени с точностью до секунды, и
        порядок внутри такой пачки был бы неопределённым.
        """
        return (
            self.session.query(SellerProfileChange)
            .order_by(SellerProfileChange.id.desc())
            .limit(limit)
            .all()
        )

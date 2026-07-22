from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProductPhoto


class SellerProductPhotoRepository:
    def __init__(self, session: Session):
        self.session = session

    def replace_for_product(self, seller_product_id: int, photo_ids: list[int]) -> None:
        """Удаляет все существующие связи под seller_product_id и вставляет
        заново с sort_order = позиция в списке. Полная замена, не diff — набор
        фото на товар приходит одной публикацией целиком."""
        self.session.query(SellerProductPhoto).filter(
            SellerProductPhoto.seller_product_id == seller_product_id
        ).delete()
        for sort_order, photo_id in enumerate(photo_ids):
            self.session.add(
                SellerProductPhoto(seller_product_id=seller_product_id, photo_id=photo_id, sort_order=sort_order)
            )
        self.session.flush()

    def list_photo_ids(self, seller_product_id: int) -> list[int]:
        rows = (
            self.session.query(SellerProductPhoto.photo_id)
            .filter(SellerProductPhoto.seller_product_id == seller_product_id)
            .order_by(SellerProductPhoto.sort_order)
            .all()
        )
        return [row[0] for row in rows]

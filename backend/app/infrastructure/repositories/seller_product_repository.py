from datetime import date, datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.infrastructure.models import Product, SellerProduct


def moderation_status_for(product_id: int | None) -> str:
    """Модерация Stage 1 — классификация: очередь модерации состоит из
    предложений без связи с Product (docs/02-domain/Catalog_Model.md,
    docs/05-ui/Admin_MVP.md). Отсюда инвариант: WAIT_PRODUCT ⟺ product_id IS NULL.

    Раньше статус жёстко ставился в WAIT_PRODUCT всем новым строкам, включая те,
    где продавец выбрал позицию из справочника корректно — статус существовал,
    но ничего не значил.
    """
    return "WAIT_PRODUCT" if product_id is None else "RESOLVED"


class SellerProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, seller_product_id: int) -> SellerProduct | None:
        return self.session.get(SellerProduct, seller_product_id)

    def list_by_seller(self, seller_id: int) -> list[SellerProduct]:
        return (
            self.session.query(SellerProduct)
            .filter(SellerProduct.seller_id == seller_id)
            .all()
        )

    def count_published(self, seller_id: int) -> int:
        return (
            self.session.query(SellerProduct)
            .filter(SellerProduct.seller_id == seller_id, SellerProduct.is_published.is_(True))
            .count()
        )

    def list_awaiting_moderation(self, *, page: int, limit: int) -> tuple[list[SellerProduct], int]:
        """Очередь модерации — предложения без связи с Product (Admin_MVP.md,
        экран 3). Фильтр по product_id, а не по moderation_status: статус
        выводится из связи, а не наоборот (см. moderation_status_for)."""
        query = self.session.query(SellerProduct).filter(SellerProduct.product_id.is_(None))
        total = query.count()
        items = (
            query.order_by(SellerProduct.created_at, SellerProduct.id)
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def list_visible_for_seller(
        self, seller_id: int, *, group_id: int | None = None, search: str | None = None, sort: str = "name"
    ) -> list[SellerProduct]:
        """Каталог одного продавца для покупателя (REST_API.md,
        `GET /catalog/sellers/{id}/products`).

        Видимость та же, что в общем каталоге: опубликованное предложение
        промодерированной и не снятой из справочника позиции. Поиск, в отличие
        от общего каталога, идёт по обоим именам — внутри каталога продавца
        покупатель ищет то, что видит на экране, включая собственное
        наименование продавца.
        """
        query = (
            self.session.query(SellerProduct)
            .join(Product, Product.id == SellerProduct.product_id)
            .filter(
                SellerProduct.seller_id == seller_id,
                SellerProduct.is_published.is_(True),
                Product.is_active.is_(True),
            )
        )
        if group_id is not None:
            query = query.filter(Product.product_group_id == group_id)
        if search:
            pattern = f"%{search}%"
            query = query.filter(or_(SellerProduct.seller_name.ilike(pattern), Product.name.ilike(pattern)))
        order = SellerProduct.price if sort == "price" else SellerProduct.seller_name
        return query.order_by(order, SellerProduct.id).all()

    def list_published_for_products(self, product_ids: list[int]) -> list[SellerProduct]:
        if not product_ids:
            return []
        return (
            self.session.query(SellerProduct)
            .filter(
                SellerProduct.product_id.in_(product_ids),
                SellerProduct.is_published.is_(True),
            )
            .order_by(SellerProduct.price, SellerProduct.id)
            .all()
        )

    def create(
        self,
        *,
        seller_id: int,
        product_id: int | None,
        seller_name: str,
        price: float,
        stock: float,
        unit: str,
        description: str | None,
        is_published: bool,
        origin_country: str | None = None,
        supply_date: date | None = None,
        seller_sku: str | None = None,
    ) -> SellerProduct:
        now = datetime.now(timezone.utc)
        seller_product = SellerProduct(
            seller_id=seller_id,
            product_id=product_id,
            seller_name=seller_name,
            price=price,
            stock=stock,
            unit=unit,
            description=description,
            origin_country=origin_country,
            supply_date=supply_date,
            seller_sku=seller_sku,
            is_published=is_published,
            moderation_status=moderation_status_for(product_id),
            created_at=now,
            updated_at=now,
        )
        self.session.add(seller_product)
        self.session.flush()
        return seller_product

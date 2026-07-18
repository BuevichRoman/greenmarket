from sqlalchemy.orm import Session

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.photo_gateway import PhotoGateway
from app.platform.seller_gateway import SellerGateway


class CatalogUseCase:
    """Публичный каталог товаров для Buyer Web (см. docs/04-services/REST_API.md, Catalog API).

    Товар считается видимым только если Product.is_active, у него есть хотя бы
    одно опубликованное предложение (SellerProduct.is_published) от активного
    продавца (Seller.is_active) — см. docs/05-ui/Buyer_MVP.md, "Предложения продавцов".

    Пагинация (list_products) выполняется в памяти после фильтрации по
    видимости — сознательное упрощение Stage 1 при текущем размере каталога
    (Seed Data: 15 групп / 16 товаров). При заметном росте каталога нужно
    перенести фильтрацию/пагинацию на уровень SQL.
    """

    def __init__(self, session: Session):
        self.session = session
        self.product_group_repository = ProductGroupRepository(session)
        self.product_repository = ProductRepository(session)
        self.seller_product_repository = SellerProductRepository(session)
        self.seller_gateway = SellerGateway(session)
        self.photo_gateway = PhotoGateway(session)

    def _visible_offers_by_product(self, product_ids: list[int]) -> dict[int, list]:
        offers = self.seller_product_repository.list_published_for_products(product_ids)
        seller_ids = list({offer.seller_id for offer in offers})
        active_seller_ids = self.seller_gateway.list_active_seller_ids(seller_ids)
        by_product: dict[int, list] = {}
        for offer in offers:
            if offer.seller_id not in active_seller_ids:
                continue
            by_product.setdefault(offer.product_id, []).append(offer)
        return by_product

    def list_groups(self) -> list[dict]:
        groups = self.product_group_repository.list_active()
        products = self.product_repository.list_active()
        offers_by_product = self._visible_offers_by_product([p.id for p in products])
        visible_product_ids = set(offers_by_product.keys())

        count_by_group: dict[int, int] = {}
        for product in products:
            if product.id in visible_product_ids:
                count_by_group[product.product_group_id] = count_by_group.get(product.product_group_id, 0) + 1

        return [
            {
                "id": group.id,
                "parent_id": group.parent_id,
                "name": group.name,
                "sort_order": group.sort_order,
                "product_count": count_by_group.get(group.id, 0),
            }
            for group in groups
        ]

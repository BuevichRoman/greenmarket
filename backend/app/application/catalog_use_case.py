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

    def list_products(
        self,
        *,
        group_id: int | None = None,
        search: str | None = None,
        sort: str = "name",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        products = self.product_repository.list_active(group_id=group_id, search=search)
        offers_by_product = self._visible_offers_by_product([p.id for p in products])
        visible_products = [p for p in products if p.id in offers_by_product]

        cheapest_offer_by_product = {
            product_id: min(offers, key=lambda o: o.price)
            for product_id, offers in offers_by_product.items()
        }

        if sort == "price":
            visible_products.sort(key=lambda p: cheapest_offer_by_product[p.id].price)
        else:
            visible_products.sort(key=lambda p: p.name)

        total = len(visible_products)
        start = (page - 1) * limit
        page_items = visible_products[start : start + limit]

        cheapest_offer_ids = [cheapest_offer_by_product[p.id].id for p in page_items]
        photos_by_seller_product = self.photo_gateway.list_by_seller_products(cheapest_offer_ids)

        items = []
        for product in page_items:
            offers = offers_by_product[product.id]
            cheapest = cheapest_offer_by_product[product.id]
            items.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "min_price": cheapest.price,
                    "offer_count": len(offers),
                    "photos": photos_by_seller_product.get(cheapest.id, []),
                }
            )
        return items, total

    def get_product(self, product_id: int) -> dict | None:
        product = self.product_repository.get_active(product_id)
        if product is None:
            return None

        offers_by_product = self._visible_offers_by_product([product_id])
        offers = offers_by_product.get(product_id, [])
        if not offers:
            return None

        offers_sorted = sorted(offers, key=lambda o: o.price)
        offer_ids = [offer.id for offer in offers_sorted]
        photos_by_seller_product = self.photo_gateway.list_by_seller_products(offer_ids)

        return {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "offers": [
                {
                    "seller_product_id": offer.id,
                    "seller_id": offer.seller_id,
                    "seller_name": offer.seller_name,
                    "price": offer.price,
                    "unit": offer.unit,
                    "stock": offer.stock,
                    "description": offer.description,
                    "photos": photos_by_seller_product.get(offer.id, []),
                }
                for offer in offers_sorted
            ],
        }

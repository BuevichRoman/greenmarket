import hashlib
import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProduct
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.seller_gateway import SellerGateway
from app.publication.catalog_change import CatalogChange
from app.publication.catalog_publication_service import CatalogPublicationService
from app.publication.publication_result import PublicationResult

logger = logging.getLogger(__name__)


class SellerCatalogPublisher:
    """Путь публикации из Seller Admin: публикует текущее состояние каталога
    продавца (ТЗ Seller Catalog API, раздел 8).

    Входного набора товаров здесь нет, и это главное отличие от публикации из
    книги: отсутствие товара в запросе никогда не означает снятие с витрины.
    Публикуется то, что уже лежит в SellerProduct, — правки приходят раньше,
    отдельными запросами каталога.

    Товар со ссылкой на снятую позицию справочника или снятую категорию тоже
    не деактивируется: он просто не проходит фильтр видимости на чтении
    (`SellerProductRepository.list_visible_for_seller`). Второй реализации
    видимости здесь нет — ТЗ прямо запрещает дублировать её в ветке публикации.
    """

    def __init__(
        self,
        session: Session,
        seller_gateway: SellerGateway,
        seller_product_repository: SellerProductRepository,
        seller_product_photo_repository: SellerProductPhotoRepository,
        catalog_publication_repository: CatalogPublicationRepository,
    ):
        self.session = session
        self.seller_product_repository = seller_product_repository
        self.seller_product_photo_repository = seller_product_photo_repository
        self.catalog_publication_service = CatalogPublicationService(
            session=session,
            seller_gateway=seller_gateway,
            catalog_publication_repository=catalog_publication_repository,
            path_logger=logger,
        )

    def publish(self, seller_id: int, published_by: int) -> PublicationResult:
        rows = self.seller_product_repository.list_by_seller(seller_id)
        # N+1 сознательно — тот же компромисс, что в публикации из книги:
        # каталог продавца на Stage 1 мал, заранее не оптимизируем.
        photo_ids = {row.id: self.seller_product_photo_repository.list_photo_ids(row.id) for row in rows}

        # Видимость считается до записи: хеш должен описывать состояние, которое
        # публикуется, а не то, из которого мы в него переходим.
        targets = {row.id: bool(photo_ids[row.id]) for row in rows}
        catalog_hash = _state_hash(rows, photo_ids, targets)

        def hidden_no_photo() -> list[str]:
            return [row.seller_name for row in rows if not photo_ids[row.id]]

        def apply_catalog() -> CatalogChange:
            updated = deactivated = 0
            for row in rows:
                target = targets[row.id]
                if row.is_published == target:
                    continue
                row.is_published = target
                if target:
                    updated += 1
                else:
                    deactivated += 1
            return CatalogChange(updated=updated, deactivated=deactivated, hidden_no_photo=hidden_no_photo())

        return self.catalog_publication_service.publish(
            seller_id,
            published_by,
            publication_key=str(uuid.uuid4()),
            catalog_hash=catalog_hash,
            mode="prod",
            apply_catalog=apply_catalog,
            describe_unchanged=lambda: CatalogChange(hidden_no_photo=hidden_no_photo()),
        )


def _state_hash(
    rows: list[SellerProduct], photo_ids: dict[int, list[int]], targets: dict[int, bool]
) -> str:
    """CatalogHash для seller-пути — SHA-256 от публикуемого состояния каталога.

    У книги хеш считается от содержимого документа (`HashCalculator`), здесь
    документа нет, поэтому хешируется сама база. Поле `Seller.current_catalog_hash`
    от этого не меняет смысла — «слепок того, что опубликовано», — но у двух
    входов слепки разной природы: после публикации из Seller Admin короткое
    замыкание «книга не изменилась» честно не сработает, потому что каталог
    действительно изменился помимо книги.

    Пустой каталог даёт стабильный хеш пустого списка — публиковать пустой
    каталог разрешено, и повторная такая публикация не должна выглядеть
    изменением.
    """
    payload = [
        {
            "id": row.id,
            "product_id": row.product_id,
            "seller_name": row.seller_name,
            "price": str(row.price),
            "stock": str(row.stock),
            "unit": row.unit,
            "description": row.description,
            "origin_country": row.origin_country,
            "supply_date": str(row.supply_date) if row.supply_date is not None else None,
            "seller_sku": row.seller_sku,
            "is_published": targets[row.id],
            "photos": photo_ids[row.id],
        }
        for row in sorted(rows, key=lambda r: r.id)
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

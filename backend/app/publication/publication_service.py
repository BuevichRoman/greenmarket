import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProduct
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.mapping.publication_model import PublicationModel, PublicationProduct
from app.platform.seller_gateway import SellerGateway
from app.publication.errors import DuplicatePublicationError, PublicationConflictError
from app.publication.publication_result import PublicationResult

_OTHER_PRODUCT_PLACEHOLDER = "Прочее"

logger = logging.getLogger(__name__)


class PublicationService:
    """Транзакционно применяет провалидированную и промапленную PublicationModel
    к базе данных GreenMarket — создаёт/обновляет SellerProduct, деактивирует
    пропавшие товары, ведёт журнал публикаций (CatalogPublication) и служебные
    данные продавца (Seller.current_publication_key/current_catalog_hash).

    Не читает Excel, не валидирует документ — предполагает, что Validator и
    Mapper уже успешно отработали (задание PR-006, kwork/timeline.md).
    """

    def __init__(
        self,
        session: Session,
        seller_gateway: SellerGateway,
        seller_product_repository: SellerProductRepository,
        product_repository: ProductRepository,
        product_group_repository: ProductGroupRepository,
        catalog_publication_repository: CatalogPublicationRepository,
    ):
        self.session = session
        self.seller_gateway = seller_gateway
        self.seller_product_repository = seller_product_repository
        self.product_repository = product_repository
        self.product_group_repository = product_group_repository
        self.catalog_publication_repository = catalog_publication_repository

    def publish(
        self, model: PublicationModel, published_by: int, *, publication_key: str, catalog_hash: str
    ) -> PublicationResult:
        seller_id = model.metadata.seller_id

        logger.info("Публикация начата: seller_id=%s publication_key=%s", seller_id, publication_key)

        try:
            if self.catalog_publication_repository.exists_with_key(publication_key):
                raise DuplicatePublicationError(
                    f"PublicationKey '{publication_key}' уже был использован в предыдущей публикации"
                )

            current_hash = self.seller_gateway.get_current_catalog_hash(seller_id)
            catalog_unchanged = current_hash is not None and catalog_hash == current_hash

            created = updated = deactivated = 0
            if not catalog_unchanged:
                created, updated, deactivated = self._apply_catalog(model.products, seller_id)

            new_version = self.catalog_publication_repository.latest_version(seller_id) + 1
            publication = self.catalog_publication_repository.create(
                seller_id=seller_id,
                version=new_version,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                published_by=published_by,
            )
            self.seller_gateway.update_current_publication(
                seller_id, publication_key=publication_key, catalog_hash=catalog_hash, catalog_version=new_version
            )

            self.session.commit()
            logger.info(
                "Публикация завершена: seller_id=%s publication_key=%s created=%s updated=%s deactivated=%s",
                seller_id, publication_key, created, updated, deactivated,
            )
            return PublicationResult(
                success=True,
                publication_id=publication.id,
                created_count=created,
                updated_count=updated,
                deactivated_count=deactivated,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
            )
        except IntegrityError as exc:
            self.session.rollback()
            if "uk_CatalogPublication_key" not in str(exc.orig):
                # Не гонка по publication_key (например FK на published_by/seller_id
                # или UNIQUE(seller_id, version)) — пробрасываем как есть, не
                # маскируем под DuplicatePublicationError.
                logger.warning("Публикация отклонена (ошибка целостности данных): seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
                raise
            # UNIQUE(publication_key) на CatalogPublication — гонка между
            # exists_with_key() и собственным INSERT (два publish() с одним
            # ключом одновременно). PublicationService по контракту
            # пробрасывает только собственные ошибки.
            logger.warning("Публикация отклонена (гонка PublicationKey): seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise DuplicatePublicationError(f"PublicationKey '{publication_key}' уже используется (конфликт при записи)") from exc
        except Exception as exc:
            self.session.rollback()
            logger.warning("Публикация отклонена: seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise

    def _apply_catalog(self, products: list[PublicationProduct], seller_id: int) -> tuple[int, int, int]:
        existing_by_id = {sp.id: sp for sp in self.seller_product_repository.list_by_seller(seller_id)}
        seen_ids: set[int] = set()
        created = updated = 0

        for item in products:
            product_id = self._resolve_product_id(item)

            if item.seller_product_id is None:
                self.seller_product_repository.create(
                    seller_id=seller_id,
                    product_id=product_id,
                    seller_name=item.seller_name,
                    price=item.price,
                    stock=item.stock,
                    unit=item.unit,
                    description=item.description,
                )
                created += 1
                continue

            existing = existing_by_id.get(item.seller_product_id)
            if existing is None or existing.seller_id != seller_id:
                raise PublicationConflictError(
                    f"SellerProductId {item.seller_product_id} не найден среди товаров продавца {seller_id}"
                )

            seen_ids.add(existing.id)
            if self._has_changed(existing, item, product_id):
                if existing.product_id != product_id:
                    # Смена товарной позиции — новая заявка на классификацию
                    # (docs/02-domain/Catalog_Template.md, "Изменение товарной
                    # позиции GreenMarket"): предыдущее решение модератора
                    # больше не относится к новой позиции.
                    existing.moderation_status = "WAIT_PRODUCT"
                    existing.moderator_id = None
                    existing.moderated_at = None
                    existing.moderation_comment = None
                existing.product_id = product_id
                existing.seller_name = item.seller_name
                existing.price = item.price
                existing.stock = item.stock
                existing.unit = item.unit
                existing.description = item.description
                existing.is_published = True
                updated += 1

        deactivated = 0
        for seller_product in existing_by_id.values():
            if seller_product.id not in seen_ids and seller_product.is_published:
                seller_product.is_published = False
                deactivated += 1

        return created, updated, deactivated

    def _resolve_product_id(self, item: PublicationProduct) -> int | None:
        if item.product_name is None or item.product_name == _OTHER_PRODUCT_PLACEHOLDER:
            return None
        group = self.product_group_repository.find_by_name(item.product_group_name)
        if group is None:
            return None
        product = next((p for p in self.product_repository.list_by_group(group.id) if p.name == item.product_name), None)
        return product.id if product else None

    def _has_changed(self, existing: SellerProduct, item: PublicationProduct, product_id: int | None) -> bool:
        return (
            not existing.is_published
            or existing.product_id != product_id
            or existing.seller_name != item.seller_name
            or float(existing.price) != item.price
            or float(existing.stock) != item.stock
            or existing.unit != item.unit
            or existing.description != item.description
        )

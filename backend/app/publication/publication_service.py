import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProduct
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
from app.infrastructure.repositories.seller_product_repository import (
    SellerProductRepository,
    moderation_status_for,
)
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
        seller_product_photo_repository: SellerProductPhotoRepository,
    ):
        self.session = session
        self.seller_gateway = seller_gateway
        self.seller_product_repository = seller_product_repository
        self.product_repository = product_repository
        self.product_group_repository = product_group_repository
        self.catalog_publication_repository = catalog_publication_repository
        self.seller_product_photo_repository = seller_product_photo_repository

    def publish(
        self, model: PublicationModel, published_by: int, *, publication_key: str, catalog_hash: str, mode: str = "prod"
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

            # Считаем по входной книге, а не внутри _apply_catalog: продавец должен
            # видеть список скрытых товаров и при повторной публикации без изменений,
            # когда _apply_catalog вообще не вызывается.
            hidden_no_photo = [product.seller_name for product in model.products if not product.photo_ids]

            new_version = self.catalog_publication_repository.latest_version(seller_id) + 1
            publication = self.catalog_publication_repository.create(
                seller_id=seller_id,
                version=new_version,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                published_by=published_by,
                created_count=created,
                updated_count=updated,
                deactivated_count=deactivated,
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
                mode=mode,
                hidden_no_photo=hidden_no_photo,
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
        existing_rows = self.seller_product_repository.list_by_seller(seller_id)
        existing_by_id = {sp.id: sp for sp in existing_rows}
        existing_by_sku = {sp.seller_sku: sp for sp in existing_rows if sp.seller_sku}
        # N+1 сознательно — размер каталога продавца на Stage 1 мал, не
        # оптимизируем заранее (YAGNI).
        existing_photo_ids_by_id = {
            sp_id: self.seller_product_photo_repository.list_photo_ids(sp_id) for sp_id in existing_by_id
        }
        seen_ids: set[int] = set()
        created = updated = 0

        for item in products:
            product_id = self._resolve_product_id(item)

            existing = self._match_existing(item, existing_by_id, existing_by_sku, seller_id)

            if existing is None:
                seller_product = self.seller_product_repository.create(
                    seller_id=seller_id,
                    product_id=product_id,
                    seller_name=item.seller_name,
                    price=item.price,
                    stock=item.stock,
                    unit=item.unit,
                    description=item.description,
                    origin_country=item.origin_country,
                    supply_date=item.supply_date,
                    seller_sku=item.seller_sku,
                    is_published=bool(item.photo_ids),
                )
                self.seller_product_photo_repository.replace_for_product(seller_product.id, item.photo_ids)
                if item.seller_sku is not None:
                    existing_by_sku[item.seller_sku] = seller_product
                created += 1
                continue

            seen_ids.add(existing.id)
            photos_changed = existing_photo_ids_by_id.get(existing.id, []) != item.photo_ids
            if self._has_changed(existing, item, product_id) or photos_changed:
                if existing.product_id != product_id:
                    # Смена товарной позиции: предыдущее решение модератора
                    # больше не относится к новой позиции (docs/02-domain/
                    # Catalog_Template.md, "Изменение товарной позиции
                    # GreenMarket"). Новый статус выводится из самой позиции —
                    # выбранная продавцом позиция классифицирует товар, пустая
                    # возвращает его в очередь модерации.
                    existing.moderation_status = moderation_status_for(product_id)
                    existing.moderator_id = None
                    existing.moderated_at = None
                    existing.moderation_comment = None
                existing.product_id = product_id
                existing.seller_name = item.seller_name
                existing.price = item.price
                existing.stock = item.stock
                existing.unit = item.unit
                existing.description = item.description
                existing.origin_country = item.origin_country
                existing.supply_date = item.supply_date
                # Пустой артикул не стирает сохранённый: у книг шаблонов 2.1/2.2
                # колонки нет физически, и публикация такой книги не должна
                # обнулять ключ, проставленный переносом или книгой 2.3.
                if item.seller_sku is not None and existing.seller_sku != item.seller_sku:
                    # Индекс ведётся вместе со строкой, иначе он разошёлся бы с
                    # состоянием внутри одной публикации: продавец, поменявший
                    # артикулы у двух строк местами, получил бы совпадение по
                    # уже занятому ключу.
                    existing_by_sku.pop(existing.seller_sku, None)
                    existing.seller_sku = item.seller_sku
                    existing_by_sku[item.seller_sku] = existing
                # Товар без фото сохраняется, но покупателю не показывается —
                # каталог обязан быть с картинками (Catalog_Template.md).
                existing.is_published = bool(item.photo_ids)
                self.seller_product_photo_repository.replace_for_product(existing.id, item.photo_ids)
                updated += 1

        deactivated = 0
        for seller_product in existing_by_id.values():
            if seller_product.id not in seen_ids and seller_product.is_published:
                seller_product.is_published = False
                deactivated += 1

        return created, updated, deactivated

    def _match_existing(
        self,
        item: PublicationProduct,
        existing_by_id: dict[int, SellerProduct],
        existing_by_sku: dict[str, SellerProduct],
        seller_id: int,
    ) -> SellerProduct | None:
        """Какому существующему товару соответствует строка книги.

        Артикул продавца главнее SellerProductId: он принадлежит продавцу и
        живёт в книге, тогда как SellerProductId сервер выдаёт, а доставить в
        книгу не может (kwork/defect_publication_recreates_rows.md) — из-за
        этого разрыва публикация и пересоздавала каталог целиком.

        Незнакомый артикул — это новый товар, а не ошибка: артикул выдаёт
        продавец. Незнакомый SellerProductId, наоборот, ошибка: его выдал
        сервер, и если его нет среди товаров продавца, книга ссылается на
        чужую или несуществующую строку.
        """
        if item.seller_sku is not None:
            existing = existing_by_sku.get(item.seller_sku)
            if existing is not None:
                return existing
            # Артикул ещё не знаком, но строка несёт SellerProductId — значит
            # это существующий товар, которому продавец только что добавил
            # артикул. Принимаем ключ на него, а не заводим дубль.

        if item.seller_product_id is None:
            return None

        existing = existing_by_id.get(item.seller_product_id)
        if existing is None or existing.seller_id != seller_id:
            raise PublicationConflictError(
                f"SellerProductId {item.seller_product_id} не найден среди товаров продавца {seller_id}"
            )
        return existing

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
            # Не «строка снята с публикации», а «её видимость должна измениться»:
            # иначе строка без фото считалась бы изменённой на каждой публикации.
            existing.is_published != bool(item.photo_ids)
            or existing.product_id != product_id
            or existing.seller_name != item.seller_name
            or float(existing.price) != item.price
            or float(existing.stock) != item.stock
            or existing.unit != item.unit
            or existing.description != item.description
            or existing.origin_country != item.origin_country
            or existing.supply_date != item.supply_date
            # Только появление или смена артикула — исчезновение колонки из
            # книги изменением не считается, иначе публикация книги 2.2
            # объявляла бы изменённой каждую строку.
            or (item.seller_sku is not None and existing.seller_sku != item.seller_sku)
        )

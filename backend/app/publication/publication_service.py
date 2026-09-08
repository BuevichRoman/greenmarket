import logging

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
from app.publication.catalog_change import CatalogChange
from app.publication.catalog_publication_service import CatalogPublicationService
from app.publication.errors import PublicationConflictError
from app.publication.publication_result import PublicationResult

_OTHER_PRODUCT_PLACEHOLDER = "Прочее"

logger = logging.getLogger(__name__)


class PublicationService:
    """Путь публикации из рабочей книги: применяет провалидированную и
    промапленную PublicationModel к базе GreenMarket — создаёт и обновляет
    SellerProduct, деактивирует пропавшие из книги товары.

    Здесь остаётся только то, что специфично для книги: сопоставление
    присланных строк с существующими и деактивация тех, которых во входном
    наборе больше нет. Общая механика публикации — версия, CatalogPublication,
    текущее состояние продавца, транзакция — вынесена в
    CatalogPublicationService и одинакова для всех входов в каталог
    (ТЗ Seller Catalog API, раздел 9).

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
        self.catalog_publication_service = CatalogPublicationService(
            session=session,
            seller_gateway=seller_gateway,
            catalog_publication_repository=catalog_publication_repository,
            path_logger=logger,
        )

    def publish(
        self, model: PublicationModel, published_by: int, *, publication_key: str, catalog_hash: str, mode: str = "prod"
    ) -> PublicationResult:
        seller_id = model.metadata.seller_id

        def hidden_no_photo() -> list[str]:
            # Считаем по входной книге, а не внутри _apply_catalog: продавец должен
            # видеть список скрытых товаров и при повторной публикации без изменений,
            # когда _apply_catalog вообще не вызывается.
            return [product.seller_name for product in model.products if not product.photo_ids]

        def apply_catalog() -> CatalogChange:
            created, updated, deactivated = self._apply_catalog(model.products, seller_id)
            return CatalogChange(
                created=created, updated=updated, deactivated=deactivated, hidden_no_photo=hidden_no_photo()
            )

        return self.catalog_publication_service.publish(
            seller_id,
            published_by,
            publication_key=publication_key,
            catalog_hash=catalog_hash,
            mode=mode,
            apply_catalog=apply_catalog,
            describe_unchanged=lambda: CatalogChange(hidden_no_photo=hidden_no_photo()),
        )

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
                # Публикация из книги — тоже изменение строки: Seller Admin,
                # прочитавший её раньше, должен получить конфликт версий, а не
                # затереть только что опубликованное.
                existing.version += 1
                self.seller_product_photo_repository.replace_for_product(existing.id, item.photo_ids)
                updated += 1

        deactivated = 0
        for seller_product in existing_by_id.values():
            if seller_product.id not in seen_ids and seller_product.is_published:
                seller_product.is_published = False
                seller_product.version += 1
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

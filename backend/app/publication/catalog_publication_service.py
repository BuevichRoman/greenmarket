import logging
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.platform.seller_gateway import SellerGateway
from app.publication.catalog_change import CatalogChange
from app.publication.errors import DuplicatePublicationError
from app.publication.publication_result import PublicationResult

logger = logging.getLogger(__name__)


class CatalogPublicationService:
    """Общая механика публикации, одинаковая для всех входов в каталог.

    Здесь живёт то, что не зависит от источника изменений: проверка
    неиспользованного PublicationKey, короткое замыкание по неизменившемуся
    CatalogHash, номер версии, запись CatalogPublication, обновление текущего
    состояния продавца и границы транзакции.

    Чем именно каталог приводится в новое состояние, решает вызывающий путь и
    передаёт сюда как `apply_catalog` (ТЗ Seller Catalog API, раздел 9):
    у книги это сверка присланных строк с существующими вместе с деактивацией
    пропавших, у Seller Admin — уже сохранённое состояние SellerProduct.
    Деактивация отсутствующих строк специфична для книги и в общий слой не
    поднимается.
    """

    def __init__(
        self,
        session: Session,
        seller_gateway: SellerGateway,
        catalog_publication_repository: CatalogPublicationRepository,
        path_logger: logging.Logger | None = None,
    ):
        self.session = session
        self.seller_gateway = seller_gateway
        self.catalog_publication_repository = catalog_publication_repository
        # Журнал ведётся от имени вызывающего пути, а не общего слоя: иначе по
        # логам нельзя отличить публикацию из книги от публикации из Seller
        # Admin, а это первое, что спрашивают при разборе инцидента.
        self.logger = path_logger or logger

    def publish(
        self,
        seller_id: int,
        published_by: int,
        *,
        publication_key: str,
        catalog_hash: str,
        mode: str,
        apply_catalog: Callable[[], CatalogChange],
        describe_unchanged: Callable[[], CatalogChange] | None = None,
    ) -> PublicationResult:
        """`describe_unchanged` вызывается вместо `apply_catalog`, когда каталог
        не изменился: счётчики нулевые, но список скрытых без фото продавец
        должен получить и при повторной публикации."""
        self.logger.info("Публикация начата: seller_id=%s publication_key=%s", seller_id, publication_key)

        try:
            if self.catalog_publication_repository.exists_with_key(publication_key):
                raise DuplicatePublicationError(
                    f"PublicationKey '{publication_key}' уже был использован в предыдущей публикации"
                )

            current_hash = self.seller_gateway.get_current_catalog_hash(seller_id)
            catalog_unchanged = current_hash is not None and catalog_hash == current_hash

            if catalog_unchanged and describe_unchanged is not None:
                change = describe_unchanged()
            elif catalog_unchanged:
                change = CatalogChange()
            else:
                change = apply_catalog()

            new_version = self.catalog_publication_repository.latest_version(seller_id) + 1
            publication = self.catalog_publication_repository.create(
                seller_id=seller_id,
                version=new_version,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                published_by=published_by,
                created_count=change.created,
                updated_count=change.updated,
                deactivated_count=change.deactivated,
            )
            self.seller_gateway.update_current_publication(
                seller_id, publication_key=publication_key, catalog_hash=catalog_hash, catalog_version=new_version
            )

            self.session.commit()
            self.logger.info(
                "Публикация завершена: seller_id=%s publication_key=%s created=%s updated=%s deactivated=%s",
                seller_id, publication_key, change.created, change.updated, change.deactivated,
            )
            return PublicationResult(
                success=True,
                publication_id=publication.id,
                created_count=change.created,
                updated_count=change.updated,
                deactivated_count=change.deactivated,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                mode=mode,
                hidden_no_photo=change.hidden_no_photo,
            )
        except IntegrityError as exc:
            self.session.rollback()
            if "uk_CatalogPublication_key" not in str(exc.orig):
                # Не гонка по publication_key (например FK на published_by/seller_id
                # или UNIQUE(seller_id, version)) — пробрасываем как есть, не
                # маскируем под DuplicatePublicationError.
                self.logger.warning("Публикация отклонена (ошибка целостности данных): seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
                raise
            # UNIQUE(publication_key) на CatalogPublication — гонка между
            # exists_with_key() и собственным INSERT (два publish() с одним
            # ключом одновременно).
            self.logger.warning("Публикация отклонена (гонка PublicationKey): seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise DuplicatePublicationError(f"PublicationKey '{publication_key}' уже используется (конфликт при записи)") from exc
        except Exception as exc:
            self.session.rollback()
            self.logger.warning("Публикация отклонена: seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise

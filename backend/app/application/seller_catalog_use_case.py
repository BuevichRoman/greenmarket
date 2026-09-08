from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProduct
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import (
    SellerProductRepository,
    moderation_status_for,
)

# Поля, которые продавец правит сам. Всё остальное в SellerProduct либо
# принадлежит модерации, либо меняется публикацией, и в запрос не принимается —
# см. ТЗ Seller Catalog API, разделы 3 и 4.
EDITABLE_FIELDS = (
    "seller_name",
    "price",
    "stock",
    "unit",
    "description",
    "origin_country",
    "supply_date",
    "seller_sku",
)


class SellerProductNotFoundError(Exception):
    """Позиции нет либо она принадлежит другому продавцу.

    Один класс на два случая намеренно: различать их снаружи означало бы
    позволить перебором идентификаторов выяснить состав чужого каталога.
    """


class ProductNotSelectableError(Exception):
    """Позиции справочника не существует или она снята с работы."""


class DuplicateSellerSkuError(Exception):
    """Артикул уже занят другой позицией этого продавца."""


class CatalogChangedError(Exception):
    """Позицию изменил кто-то другой между чтением и записью.

    Отличается от повтора собственной операции: повтор создания с тем же
    ключом идемпотентности — успех, а это внешнее изменение, и решение,
    принятое по старым данным, применять нельзя (ТЗ «Безопасная двухсторонняя
    синхронизация», разделы 17 и 20).
    """


class SellerCatalogUseCase:
    """Правка каталога продавцом из Seller Admin.

    Модерация здесь не решение, а следствие: статус выводится из выбранной
    товарной позиции (`moderation_status_for`), и продавец не может назначить
    его сам. Витрину этот сценарий тоже не трогает — `is_published` меняет
    только публикация.
    """

    def __init__(self, session: Session):
        self.session = session
        self.seller_product_repository = SellerProductRepository(session)
        self.product_repository = ProductRepository(session)

    def create(self, seller_id: int, fields: dict, *, idempotency_key: str | None = None) -> SellerProduct:
        if idempotency_key is not None:
            # Повтор той же логической операции: сеть могла потерять ответ уже
            # после того, как сервер создал позицию. Возвращаем созданное
            # первой попыткой, а не применяем присланное тело заново.
            existing = self.seller_product_repository.find_by_idempotency_key(seller_id, idempotency_key)
            if existing is not None:
                return existing

        product_id = fields.get("product_id")
        self._require_selectable(product_id)

        with self._sku_conflict_guard():
            return self.seller_product_repository.create(
                seller_id=seller_id,
                product_id=product_id,
                seller_name=fields["seller_name"],
                price=fields["price"],
                stock=fields["stock"],
                unit=fields["unit"],
                description=fields.get("description"),
                origin_country=fields.get("origin_country"),
                supply_date=fields.get("supply_date"),
                seller_sku=fields.get("seller_sku"),
                idempotency_key=idempotency_key,
                # Новая позиция на витрину сама не выходит: публикация —
                # отдельная операция, и фотографии к этому моменту ещё нет.
                is_published=False,
            )

    def update(
        self,
        seller_id: int,
        seller_product_id: int,
        changes: dict,
        *,
        expected_version: int | None = None,
    ) -> SellerProduct:
        """`changes` содержит только реально присланные ключи: отсутствие ключа
        означает «не трогать», а `None` — очистить поле.

        `expected_version` — версия, которую клиент видел при чтении. Если
        строку успели изменить, запись не выполняется: решение принималось по
        данным, которых больше нет. Без токена действует прежнее поведение
        last-write-wins.
        """
        found = self.seller_product_repository.find_for_seller_admin(seller_id, seller_product_id)
        if found is None:
            raise SellerProductNotFoundError(f"Позиция каталога {seller_product_id} не найдена")
        row = found[0]

        if expected_version is not None and row.version != expected_version:
            raise CatalogChangedError(
                f"Позиция изменена: ожидалась версия {expected_version}, текущая {row.version}"
            )

        before = _revision_of(row)

        if "product_id" in changes:
            self._apply_product_change(row, changes["product_id"])

        for field in EDITABLE_FIELDS:
            if field in changes:
                setattr(row, field, changes[field])

        if _revision_of(row) != before:
            # Версия — ревизия содержимого, а не счётчик запросов: повторная
            # отправка тех же значений не должна ронять чужие решения.
            row.version += 1
            row.updated_at = datetime.now(timezone.utc)

        with self._sku_conflict_guard():
            self.session.flush()
        return row

    def _apply_product_change(self, row: SellerProduct, product_id: int | None) -> None:
        self._require_selectable(product_id)
        if row.product_id == product_id:
            return
        # Прежнее решение модератора относилось к другой позиции справочника и
        # к новой отношения не имеет (Catalog_Template.md, «Изменение товарной
        # позиции GreenMarket») — то же правило, что при публикации из книги.
        row.product_id = product_id
        row.moderation_status = moderation_status_for(product_id)
        row.moderator_id = None
        row.moderated_at = None
        row.moderation_comment = None

    def _require_selectable(self, product_id: int | None) -> None:
        if product_id is None:
            return
        if self.product_repository.get_active(product_id) is None:
            raise ProductNotSelectableError(
                f"Позиция справочника {product_id} не существует или снята с работы"
            )

    class _SkuConflictGuard:
        def __init__(self, session: Session):
            self.session = session

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            if exc_type is None or not isinstance(exc, IntegrityError):
                return False
            if "uk_SellerProduct_seller_sku" not in str(exc.orig):
                return False
            # Уникальность артикула ТЗ не проверяет, но она есть в базе
            # (миграция 018): артикул — ключ сопоставления при публикации из
            # книги. Без этого перевода конфликт уходил бы наружу как 500.
            self.session.rollback()
            raise DuplicateSellerSkuError("Артикул уже занят другой позицией этого продавца") from exc

    def _sku_conflict_guard(self) -> "_SkuConflictGuard":
        return self._SkuConflictGuard(self.session)


def _revision_of(row: SellerProduct) -> tuple:
    """Слепок значимых полей строки — по нему решается, изменилось ли
    содержимое. `product_id` входит: смена товарной позиции меняет и то, что
    видит покупатель, и статус модерации."""
    return (row.product_id, *(getattr(row, field) for field in EDITABLE_FIELDS))

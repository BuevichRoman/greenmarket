from typing import ClassVar

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SellerCatalogItem(BaseModel):
    """Строка каталога продавца в Seller Admin.

    Два имени рядом и оба нужны: `seller_name` — как товар назвал продавец,
    `product_name` — эталонное наименование позиции справочника. Пока позиция
    не сопоставлена, эталонного имени и категории не существует, поэтому они
    и приходят пустыми, а не подставляются заглушкой.
    """

    id: int
    product_id: int | None
    product_name: str | None
    product_group_id: int | None
    product_group_name: str | None
    seller_name: str
    price: Decimal
    stock: Decimal
    unit: str
    description: str | None
    origin_country: str | None
    supply_date: date | None
    seller_sku: str | None
    is_published: bool
    moderation_status: str
    updated_at: datetime
    # Токен оптимистической блокировки: клиент возвращает его в PATCH, чтобы
    # не затереть чужое изменение, случившееся между чтением и записью.
    version: int


class SellerCatalogListResponse(BaseModel):
    items: list[SellerCatalogItem]
    total: int
    page: int
    page_size: int


class SellerCatalogDetail(SellerCatalogItem):
    """То же плюс фотографии — карточке редактирования они нужны, списку нет."""

    photos: list[str] = []


class SellerProductGroupOption(BaseModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int


class SellerProductGroupListResponse(BaseModel):
    items: list[SellerProductGroupOption]


class ProductSuggestion(BaseModel):
    id: int
    name: str
    product_group_id: int
    product_group_name: str


class ProductSuggestListResponse(BaseModel):
    items: list[ProductSuggestion]


class SellerProductCreateRequest(BaseModel):
    """Тело POST /seller/products.

    Лишние ключи запрещены: молчаливое игнорирование опечатки в имени поля
    неотличимо от успешного сохранения. Заодно это и есть отказ принимать от
    клиента `seller_id`, `is_published` и поля модерации — они просто не
    описаны, и любая попытка их прислать даёт 422.
    """

    model_config = ConfigDict(extra="forbid")

    seller_name: str
    price: Decimal = Field(ge=0)
    stock: Decimal = Field(ge=0)
    unit: str
    product_id: int | None = None
    description: str | None = None
    origin_country: str | None = None
    supply_date: date | None = None
    seller_sku: str | None = None
    # Ключ идемпотентности живёт в книге продавца и переживает retry: потеря
    # ответа после успешного создания не должна плодить дубли.
    idempotency_key: str | None = Field(default=None, max_length=64)


class SellerProductUpdateRequest(BaseModel):
    """Тело PATCH /seller/products/{id} — частичное изменение.

    Отсутствие ключа означает «не трогать», явный `null` — очистить поле.
    Различить эти два случая позволяет `model_fields_set`, поэтому у всех полей
    один и тот же дефолт `None`, а не разные заглушки.
    """

    model_config = ConfigDict(extra="forbid")

    seller_name: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    stock: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    product_id: int | None = None
    description: str | None = None
    origin_country: str | None = None
    supply_date: date | None = None
    seller_sku: str | None = None
    # Версия, которую клиент видел при чтении. Обязательна: защита от гонки —
    # инвариант этого API, а не возможность по желанию. Необязательный токен
    # означал бы два режима одного эндпоинта, и обойти защиту можно было бы
    # случайно, просто не прислав поле. Не поле каталога — в changes() не
    # попадает.
    expected_version: int

    # Обнулить эти поля нечем: у товара всегда есть наименование, цена, остаток
    # и единица измерения. Явный null в них — ошибка клиента, а не очистка.
    NOT_NULLABLE: ClassVar[tuple[str, ...]] = ("seller_name", "price", "stock", "unit")

    def changes(self) -> dict:
        return {
            name: getattr(self, name)
            for name in self.model_fields_set
            if name != "expected_version"
        }

    def nulled_non_nullable(self) -> list[str]:
        return [name for name in self.NOT_NULLABLE if name in self.model_fields_set and getattr(self, name) is None]


class SellerProductPhotoResponse(BaseModel):
    """Ответ на загрузку фотографии.

    Состав идёт от существующей модели проекта, как и требует ТЗ: у
    `SellerProductPhoto` ключ составной, отдельного `id` в ней нет, а порядок
    показа называется `sort_order`. Поэтому вместо `id`/`position` из текста ТЗ
    здесь пара `seller_product_id`/`photo_id` и `sort_order` — переименовывать
    поля модели ради формулировки было бы хуже.
    """

    seller_product_id: int
    photo_id: int
    url: str
    sort_order: int

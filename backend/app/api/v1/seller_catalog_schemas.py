from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


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

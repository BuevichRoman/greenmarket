from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ProductGroupItem(BaseModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int
    product_count: int


class ProductGroupsResponse(BaseModel):
    groups: list[ProductGroupItem]


class ProductListItem(BaseModel):
    id: int
    name: str
    min_price: Decimal
    offer_count: int
    photos: list[str]


class ProductListResponse(BaseModel):
    products: list[ProductListItem]
    page: int
    limit: int
    total: int


class SellerOfferItem(BaseModel):
    seller_product_id: int
    seller_id: int
    seller_name: str
    price: Decimal
    unit: str
    stock: Decimal
    description: str | None
    # Оба поля относятся к предложению продавца, а не к товарной позиции: один
    # и тот же товар у разных продавцов из разных стран и разной свежести.
    origin_country: str | None
    supply_date: date | None
    photos: list[str]


class MarketItem(BaseModel):
    """Место торговли в карточке продавца: рынок или отдельно стоящая лавка
    (`type`). Координаты могут быть не сняты — тогда точка показывается
    адресом, но на карту не ставится."""

    id: int
    name: str
    type: str
    address: str
    latitude: Decimal | None
    longitude: Decimal | None


class MapMarketItem(BaseModel):
    """Точка на карте. Координаты не nullable, в отличие от карточки продавца:
    точку без координат на карту не поставить, и в выдачу она не попадает."""

    id: int
    name: str
    type: str
    address: str
    latitude: Decimal
    longitude: Decimal
    seller_count: int


class MapMarketListResponse(BaseModel):
    markets: list[MapMarketItem]


class MarketSellerItem(BaseModel):
    """Продавец в списке по нажатию на пин. Ряд и место пусты у лавки — там их
    нет; у рынка они и помогают найти продавца внутри."""

    seller_id: int
    name: str
    row: str | None
    place: str | None
    working_hours: str | None
    short_description: str | None
    product_count: int


class MarketSellerListResponse(BaseModel):
    sellers: list[MarketSellerItem]


class SellerCardResponse(BaseModel):
    """Карточка продавца в Customer UI. `status` не отдаётся: неактивный
    продавец покупателю просто не существует (404)."""

    seller_id: int
    name: str
    market: MarketItem | None
    row: str | None
    place: str | None
    working_hours: str | None
    short_description: str | None
    phone: str | None
    whatsapp: str | None


class SellerCatalogItem(BaseModel):
    """Предложение в каталоге одного продавца. Имён два: `name` — собственное
    наименование продавца, `catalog_name` — эталонное имя товарной позиции.
    Поле `seller_name` здесь сознательно не используется: в `SellerOfferItem`
    оно означает имя продавца, и второй смысл у того же имени в одном API —
    источник ошибок."""

    seller_product_id: int
    product_id: int
    name: str
    catalog_name: str
    group_id: int
    group_name: str
    price: Decimal
    unit: str
    stock: Decimal
    description: str | None
    origin_country: str | None
    supply_date: date | None
    photos: list[str]


class SellerCatalogResponse(BaseModel):
    products: list[SellerCatalogItem]
    page: int
    limit: int
    total: int


class ProductDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None
    group_id: int
    group_name: str
    offers: list[SellerOfferItem]

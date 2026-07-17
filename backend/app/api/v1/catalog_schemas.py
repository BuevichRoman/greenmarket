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
    photos: list[str]


class ProductDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None
    offers: list[SellerOfferItem]

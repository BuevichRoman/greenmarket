from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AdminActivationRequest(BaseModel):
    activation_code: str


class AdminActivationResponse(BaseModel):
    access_token: str


class AdminIdentityResponse(BaseModel):
    admin_id: int
    user_id: int


class SellerOnboardingRequest(BaseModel):
    user_id: int


class SellerActivationCodeResponse(BaseModel):
    seller_id: int
    activation_code: str


class SellerSummary(BaseModel):
    seller_id: int
    user_id: int
    name: str
    is_active: bool
    current_catalog_version: int
    activated_at: datetime | None
    activation_code_expires_at: datetime | None


class SellerListResponse(BaseModel):
    sellers: list[SellerSummary]


class ProductGroupSummary(BaseModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int
    is_active: bool
    product_count: int


class ProductGroupListResponse(BaseModel):
    groups: list[ProductGroupSummary]


class ProductGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    sort_order: int = 0


class ProductGroupUpdateRequest(BaseModel):
    """Правится только то, что реально пришло в теле (`model_fields_set`):
    `{"parent_id": null}` переносит группу в корень, а отсутствие ключа
    оставляет родителя как есть — иначе эти два случая неразличимы."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ProductSummary(BaseModel):
    id: int
    product_group_id: int
    group_name: str
    name: str
    description: str | None
    is_active: bool
    offer_count: int


class ProductListResponse(BaseModel):
    products: list[ProductSummary]
    page: int
    limit: int
    total: int


class ProductCreateRequest(BaseModel):
    product_group_id: int
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None


class ModerationQueueItem(BaseModel):
    """Позиция очереди. `name` — наименование товара, как его дал продавец
    (столбец `SellerProduct.seller_name`), `seller_name` — имя самого продавца,
    как в Catalog API: в БД эти два смысла носят похожие названия."""

    seller_product_id: int
    seller_id: int
    seller_name: str
    name: str
    description: str | None
    price: Decimal
    unit: str
    is_published: bool
    moderation_status: str
    created_at: datetime
    photos: list[str]


class ModerationQueueResponse(BaseModel):
    items: list[ModerationQueueItem]
    page: int
    limit: int
    total: int


class ModerationResolveRequest(BaseModel):
    product_id: int
    comment: str | None = None


class ModerationResolveResponse(BaseModel):
    seller_product_id: int
    product_id: int
    moderation_status: str
    moderator_id: int
    moderated_at: datetime
    moderation_comment: str | None


class ProductUpdateRequest(BaseModel):
    product_group_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    is_active: bool | None = None

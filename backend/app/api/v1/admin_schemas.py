from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


class AdminSellerProfileResponse(BaseModel):
    """Профиль глазами администратора. От продавцовского `SellerProfileResponse`
    отличается отсутствием `suggested_phone`: подсказка учётного номера нужна
    форме продавца при первом заполнении, администратору она только мешает —
    он правит чужой профиль, а не заполняет свой.

    `status` в ответе есть именно потому, что деактивированный продавец
    администратору отдаётся (в отличие от покупательской карточки): чаще всего
    правят как раз такого, и деактивация должна быть видна, а не угадываться.
    """

    seller_id: int
    name: str
    status: str
    row: str | None
    place: str | None
    working_hours: str | None
    short_description: str | None
    phone: str | None
    whatsapp: str | None


class AdminSellerProfileUpdateRequest(BaseModel):
    """Тот же набор полей, что у продавца, но без access_token — админ
    аутентифицируется заголовком Authorization (см. REST_API.md, Admin API).

    `extra="forbid"` — по той же причине, что и у `SellerProfileUpdateRequest`:
    иначе опечатка в имени поля давала бы 422 продавцу и молчаливые 200
    администратору поверх одного и того же сервиса.
    """

    model_config = ConfigDict(extra="forbid")

    row: str | None = None
    place: str | None = None
    working_hours: str | None = None
    short_description: str | None = None
    phone: str | None = None
    whatsapp: str | None = None

    def changed_values(self) -> dict[str, str | None]:
        return self.model_dump(exclude_unset=True)


class AdminSellerProfileUpdateResponse(BaseModel):
    seller_id: int
    changed: list[str]


class SellerProfileChangeItem(BaseModel):
    id: int
    seller_id: int
    seller_name: str
    field: str
    old_value: str | None
    new_value: str | None
    author_user_id: int
    author_role: str
    created_at: datetime


class SellerProfileChangeFeedResponse(BaseModel):
    """`total` считается по тому же условию, что и `changes` (включая
    `after_id`): без него клиент не отличит полную страницу от обрезанной, а
    одна правка шести полей вытесняет из выдачи всё остальное."""

    changes: list[SellerProfileChangeItem]
    total: int


class ProductUpdateRequest(BaseModel):
    product_group_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    is_active: bool | None = None

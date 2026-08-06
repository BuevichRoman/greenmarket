from datetime import datetime

from pydantic import BaseModel


class SellerStatusResponse(BaseModel):
    seller_id: int
    is_active: bool
    current_catalog_version: int
    published_product_count: int
    last_published_at: datetime | None


class SellerActivationRequest(BaseModel):
    activation_code: str
    spreadsheet_id: str


class SellerActivationResponse(BaseModel):
    access_token: str


class SellerProfileResponse(BaseModel):
    """Профиль продавца в терминах Seller_Profile.md, §4–5.

    `name` и `status` только для чтения: имя — учётное `users.name` платформы,
    статус меняется отдельными админскими операциями activate/deactivate.
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
    suggested_phone: str | None


class SellerProfileUpdateRequest(BaseModel):
    """Правятся только переданные поля: отсутствие ключа — «не трогать»,
    пустая строка — «очистить»."""

    access_token: str
    row: str | None = None
    place: str | None = None
    working_hours: str | None = None
    short_description: str | None = None
    phone: str | None = None
    whatsapp: str | None = None

    def changed_values(self) -> dict[str, str | None]:
        return self.model_dump(exclude={"access_token"}, exclude_unset=True)


class SellerProfileUpdateResponse(BaseModel):
    changed: list[str]

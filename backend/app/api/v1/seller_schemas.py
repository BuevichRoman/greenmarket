from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    # Строкой, а не числом: значение хранится в платформенном users_prop, и
    # форма книги подставляет его в выпадающий список как есть.
    market_id: str | None
    suggested_phone: str | None


class SellerProfileUpdateRequest(BaseModel):
    """Правятся только переданные поля: отсутствие ключа — «не трогать».
    Очищают поле одинаково `null`, пустая строка и строка из одних пробелов —
    по типу `str | None` кажется, что эти случаи различаются, но нет.

    Лишние ключи запрещены (`extra="forbid"`), потому что молчаливое
    игнорирование опечатки в имени поля неотличимо от успешного сохранения.
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str
    row: str | None = None
    place: str | None = None
    working_hours: str | None = None
    short_description: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    market_id: str | None = None

    def changed_values(self) -> dict[str, str | None]:
        return self.model_dump(exclude={"access_token"}, exclude_unset=True)


class MarketOption(BaseModel):
    """Пункт выпадающего списка рынков в форме профиля. Координаты форме не
    нужны — она их не показывает и не правит."""

    id: int
    name: str
    address: str


class MarketListResponse(BaseModel):
    markets: list[MarketOption]


class SellerProfileUpdateResponse(BaseModel):
    """`changed` — поля, значение которых реально стало другим. Пустой список
    это успех, а не отказ: повторная отправка формы без правок сохранять
    нечего."""

    changed: list[str]

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SyncSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Ключ живёт у клиента и переживает retry: потеря ответа после успешного
    # создания не должна плодить вторую сессию.
    idempotency_key: str | None = Field(default=None, max_length=64)


class SyncSessionResponse(BaseModel):
    session_id: str
    status: str
    # Наличие снимка — признак, а не пятый статус: сессия остаётся ACTIVE и до,
    # и после его создания.
    baseline_ready: bool
    # Разошлись ли версии позиций с момента снимка. Само по себе расхождение
    # ошибкой не является — после снимка база и книга и должны расходиться.
    db_changed_since_baseline: bool
    created_at: datetime
    expires_at: datetime


class BaselineCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Отпечаток книги, посчитанный клиентом. Обязателен: это шлюз, а не
    # справочное поле — без доказанного равенства снимок не создаётся.
    sheet_catalog_hash: str


class BaselineItem(BaseModel):
    seller_product_id: int
    seller_sku: str | None
    product_id: int | None
    seller_name: str
    price: Decimal
    stock: Decimal
    unit: str
    description: str | None
    origin_country: str | None
    supply_date: date | None
    is_published: bool
    version: int


class BaselineResponse(BaseModel):
    session_id: str
    created_at: datetime
    items: list[BaselineItem]

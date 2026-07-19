import json
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class SellerAccess:
    seller_id: int
    published_by: int
    name: str


def resolve_seller_access(access_token: str, *, tokens_json: str | None = None) -> SellerAccess | None:
    """Резолвит access_token продавца в (seller_id, published_by) — единственный
    источник этой связки на стороне API: клиент больше не передаёт seller_id/
    published_by напрямую (иначе любой мог опубликовать каталог от чужого имени).

    Маппинг токенов приходит из SELLER_ACCESS_TOKENS (JSON в .env, не в git —
    это данные о реальных продавцах)."""
    raw = tokens_json if tokens_json is not None else settings.seller_access_tokens
    tokens: dict = json.loads(raw)
    entry = tokens.get(access_token)
    if entry is None:
        return None
    return SellerAccess(seller_id=entry["seller_id"], published_by=entry["published_by"], name=entry["name"])

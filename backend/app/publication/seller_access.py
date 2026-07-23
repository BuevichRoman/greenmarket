from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.platform.seller_gateway import SellerGateway


@dataclass(frozen=True)
class SellerAccess:
    seller_id: int
    published_by: int
    name: str


def resolve_seller_access(access_token: str, session: Session) -> SellerAccess | None:
    """Резолвит access_token продавца в (seller_id, published_by) через
    SellerGateway (Anti-Corruption Layer к таблице Seller) — единственный
    источник этой связки на стороне API: клиент не передаёт seller_id/
    published_by напрямую (иначе любой мог опубликовать каталог от чужого
    имени). access_token хранится в Seller.access_token, выдаётся через
    POST /api/v1/seller/activate — не в .env/SELLER_ACCESS_TOKENS, см.
    docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md."""
    row = SellerGateway(session).find_by_access_token(access_token)
    if row is None:
        return None
    return SellerAccess(seller_id=row.seller_id, published_by=row.user_id, name=row.name)

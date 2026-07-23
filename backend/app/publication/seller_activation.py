import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.platform.seller_gateway import SellerGateway

ACTIVATION_CODE_TTL_DAYS = 7


def issue_activation_code(seller_id: int, *, session: Session, ttl_days: int = ACTIVATION_CODE_TTL_DAYS) -> str | None:
    """Админская операция: генерирует новый одноразовый activation_code для
    существующего Seller, затирая предыдущий (если был). Не коммитит —
    вызывающий код (CLI-скрипт) отвечает за commit()."""
    gateway = SellerGateway(session)
    if gateway.get_status(seller_id) is None:
        return None

    code = secrets.token_hex(4)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=ttl_days)
    gateway.set_activation_code(seller_id, activation_code=code, expires_at=expires_at)
    return code


def activate_seller(activation_code: str, *, spreadsheet_id: str, session: Session) -> str | None:
    """Резолвит одноразовый activation_code в постоянный access_token и
    привязывает конкретную копию Google Sheets продавца (spreadsheet_id).
    Не коммитит — вызывающий код (API-эндпоинт) отвечает за commit()."""
    gateway = SellerGateway(session)
    lookup = gateway.find_by_activation_code(activation_code)
    if lookup is None:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if lookup.activation_code_expires_at is None or lookup.activation_code_expires_at < now:
        return None

    access_token = secrets.token_urlsafe(32)
    gateway.set_access_token(lookup.seller_id, access_token=access_token, spreadsheet_id=spreadsheet_id)
    return access_token

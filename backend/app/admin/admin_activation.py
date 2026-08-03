import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.infrastructure.repositories.administrator_repository import AdministratorRepository

ACTIVATION_CODE_TTL_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def issue_admin_activation_code(
    admin_id: int, *, session: Session, ttl_days: int = ACTIVATION_CODE_TTL_DAYS
) -> str | None:
    """Выдаёт новый одноразовый код активации существующему администратору,
    затирая предыдущий. Не коммитит — за commit() отвечает вызывающий (CLI).

    Код длиннее продавцовского (`secrets.token_hex(8)` против `token_hex(4)`):
    у администратора шире права, а перебор кода — единственный барьер между
    посторонним и постоянным токеном на весь Admin API.
    """
    administrator = AdministratorRepository(session).find_by_id(admin_id)
    if administrator is None:
        return None

    code = secrets.token_hex(8)
    administrator.activation_code = code
    administrator.activation_code_expires_at = _now() + timedelta(days=ttl_days)
    session.flush()
    return code


def activate_admin(activation_code: str, *, session: Session) -> str | None:
    """Меняет одноразовый код активации на постоянный access_token.

    Возвращает None одинаково для неизвестного, просроченного и уже
    использованного кода, а также для отозванного администратора
    (`is_active = FALSE`) — вызывающему не сообщается, какая именно из причин
    сработала.
    """
    administrator = AdministratorRepository(session).find_by_activation_code(activation_code)
    if administrator is None or not administrator.is_active:
        return None

    if administrator.activation_code_expires_at is None or administrator.activation_code_expires_at < _now():
        return None

    access_token = secrets.token_urlsafe(32)
    administrator.access_token = access_token
    administrator.activation_code = None
    administrator.activation_code_expires_at = None
    administrator.activated_at = _now()
    session.flush()
    return access_token

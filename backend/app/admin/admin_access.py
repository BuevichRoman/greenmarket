from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.infrastructure.repositories.administrator_repository import AdministratorRepository


@dataclass(frozen=True)
class AdminAccess:
    admin_id: int
    user_id: int


def resolve_admin_access(access_token: str, session: Session) -> AdminAccess | None:
    """Резолвит access_token администратора в (admin_id, user_id) — тот же
    принцип, что и `resolve_seller_access`: вызывающий не называет себя сам.

    `user_id` — платформенный `users.id_user`: именно он пишется в
    `SellerProduct.moderator_id` при модерации (FK, миграция 005).

    Отозванный администратор (`is_active = FALSE`) не резолвится, даже если
    его старый токен ещё у него на руках.
    """
    administrator = AdministratorRepository(session).find_by_access_token(access_token)
    if administrator is None or not administrator.is_active:
        return None
    return AdminAccess(admin_id=administrator.id, user_id=administrator.user_id)

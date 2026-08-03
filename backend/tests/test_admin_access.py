from sqlalchemy import text

from app.admin.admin_access import resolve_admin_access


def insert_admin(session, *, name: str, access_token: str, is_active: bool = True) -> tuple[int, int]:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id, access_token, is_active) VALUES (:user_id, :token, :is_active)"),
        {"user_id": user_id, "token": access_token, "is_active": is_active},
    ).lastrowid
    return admin_id, user_id


def test_resolve_admin_access_returns_admin_and_platform_user(session):
    admin_id, user_id = insert_admin(session, name="Админ резолв", access_token="token-resolve-ok")

    access = resolve_admin_access("token-resolve-ok", session)

    assert access is not None
    assert access.admin_id == admin_id
    assert access.user_id == user_id


def test_resolve_admin_access_returns_none_for_unknown_token(session):
    assert resolve_admin_access("no-such-token", session) is None


def test_resolve_admin_access_returns_none_for_empty_token(session):
    """Пустой токен не должен матчиться на записи с NULL/пустым access_token —
    иначе любой неактивированный админ давал бы доступ без токена вообще."""
    insert_admin(session, name="Админ без токена", access_token="")

    assert resolve_admin_access("", session) is None


def test_resolve_admin_access_returns_none_for_deactivated_admin(session):
    insert_admin(session, name="Отозванный админ", access_token="token-revoked", is_active=False)

    assert resolve_admin_access("token-revoked", session) is None

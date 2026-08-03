from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.admin.admin_activation import activate_admin, issue_admin_activation_code


def insert_admin(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def test_issue_activation_code_sets_code_and_future_expiry(session):
    admin_id = insert_admin(session, name="Админ для выдачи кода")

    code = issue_admin_activation_code(admin_id, session=session)

    assert code is not None
    row = session.execute(
        text("SELECT activation_code, activation_code_expires_at FROM Administrator WHERE id = :id"), {"id": admin_id}
    ).first()
    assert row[0] == code
    assert row[1] > datetime.now(timezone.utc).replace(tzinfo=None)


def test_issue_activation_code_returns_none_for_missing_admin(session):
    assert issue_admin_activation_code(999_999, session=session) is None


def test_issue_activation_code_overwrites_previous_code(session):
    admin_id = insert_admin(session, name="Админ для перевыпуска кода")
    first_code = issue_admin_activation_code(admin_id, session=session)

    second_code = issue_admin_activation_code(admin_id, session=session)

    assert second_code != first_code
    row = session.execute(text("SELECT activation_code FROM Administrator WHERE id = :id"), {"id": admin_id}).first()
    assert row[0] == second_code


def test_activate_admin_returns_access_token_and_burns_code(session):
    admin_id = insert_admin(session, name="Админ для активации")
    code = issue_admin_activation_code(admin_id, session=session)

    access_token = activate_admin(code, session=session)

    assert access_token is not None
    row = session.execute(
        text("SELECT access_token, activation_code, activated_at FROM Administrator WHERE id = :id"), {"id": admin_id}
    ).first()
    assert row[0] == access_token
    assert row[1] is None
    assert row[2] is not None


def test_activate_admin_returns_none_for_unknown_code(session):
    assert activate_admin("does-not-exist", session=session) is None


def test_activate_admin_returns_none_for_expired_code(session):
    admin_id = insert_admin(session, name="Админ с просроченным кодом")
    expired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.execute(
        text("UPDATE Administrator SET activation_code = :code, activation_code_expires_at = :expires_at WHERE id = :id"),
        {"code": "expired-code", "expires_at": expired_at, "id": admin_id},
    )

    assert activate_admin("expired-code", session=session) is None


def test_activate_admin_code_is_single_use(session):
    admin_id = insert_admin(session, name="Админ одноразовый код")
    code = issue_admin_activation_code(admin_id, session=session)
    first_token = activate_admin(code, session=session)
    assert first_token is not None

    second_token = activate_admin(code, session=session)

    assert second_token is None


def test_activate_admin_refuses_deactivated_admin(session):
    """Отзыв доступа: is_active = FALSE должен закрывать и повторную активацию,
    иначе отозванный админ вернул бы себе токен собственным кодом."""
    admin_id = insert_admin(session, name="Отозванный админ активация")
    code = issue_admin_activation_code(admin_id, session=session)
    session.execute(text("UPDATE Administrator SET is_active = FALSE WHERE id = :id"), {"id": admin_id})

    assert activate_admin(code, session=session) is None

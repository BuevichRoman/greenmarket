from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.publication.seller_activation import activate_seller, issue_activation_code


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def test_issue_activation_code_sets_code_and_future_expiry(session):
    seller_id = insert_seller(session, name="Продавец для выдачи кода")

    code = issue_activation_code(seller_id, session=session)

    assert code is not None
    row = session.execute(
        text("SELECT activation_code, activation_code_expires_at FROM Seller WHERE id = :id"), {"id": seller_id}
    ).first()
    assert row[0] == code
    assert row[1] > datetime.now(timezone.utc).replace(tzinfo=None)


def test_issue_activation_code_returns_none_for_missing_seller(session):
    assert issue_activation_code(999_999, session=session) is None


def test_issue_activation_code_overwrites_previous_code(session):
    seller_id = insert_seller(session, name="Продавец для перевыпуска кода")
    first_code = issue_activation_code(seller_id, session=session)

    second_code = issue_activation_code(seller_id, session=session)

    assert second_code != first_code
    row = session.execute(text("SELECT activation_code FROM Seller WHERE id = :id"), {"id": seller_id}).first()
    assert row[0] == second_code


def test_activate_seller_returns_access_token_for_valid_code(session):
    seller_id = insert_seller(session, name="Продавец для активации")
    code = issue_activation_code(seller_id, session=session)

    access_token = activate_seller(code, spreadsheet_id="sheet-123", session=session)

    assert access_token is not None
    row = session.execute(
        text("SELECT access_token, spreadsheet_id, activation_code FROM Seller WHERE id = :id"), {"id": seller_id}
    ).first()
    assert row[0] == access_token
    assert row[1] == "sheet-123"
    assert row[2] is None


def test_activate_seller_returns_none_for_unknown_code(session):
    assert activate_seller("does-not-exist", spreadsheet_id="sheet-x", session=session) is None


def test_activate_seller_returns_none_for_expired_code(session):
    seller_id = insert_seller(session, name="Продавец с просроченным кодом")
    expired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.execute(
        text("UPDATE Seller SET activation_code = :code, activation_code_expires_at = :expires_at WHERE id = :id"),
        {"code": "expired-code", "expires_at": expired_at, "id": seller_id},
    )

    assert activate_seller("expired-code", spreadsheet_id="sheet-y", session=session) is None


def test_activate_seller_code_is_single_use(session):
    seller_id = insert_seller(session, name="Продавец одноразовый код")
    code = issue_activation_code(seller_id, session=session)
    first_token = activate_seller(code, spreadsheet_id="sheet-1", session=session)
    assert first_token is not None

    second_token = activate_seller(code, spreadsheet_id="sheet-2", session=session)

    assert second_token is None

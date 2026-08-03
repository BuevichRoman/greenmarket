from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.admin.seller_onboarding import SellerAlreadyExistsError, UserNotFoundError, onboard_seller


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def test_onboard_creates_seller_and_returns_activation_code(session):
    user_id = insert_user(session, name="Фермер для онбординга")

    result = onboard_seller(user_id, session=session)

    assert result.seller_id > 0
    assert result.activation_code
    row = session.execute(
        text("SELECT user_id, is_active, activation_code, activation_code_expires_at FROM Seller WHERE id = :id"),
        {"id": result.seller_id},
    ).first()
    assert row[0] == user_id
    assert row[1] == 1
    assert row[2] == result.activation_code
    assert row[3] > datetime.now(timezone.utc).replace(tzinfo=None)


def test_onboard_rejects_unknown_platform_user(session):
    """Продавец обязан ссылаться на существующего пользователя платформы —
    FK не даст создать запись, но диагностика должна быть человеческой,
    а не ошибкой целостности из драйвера."""
    with pytest.raises(UserNotFoundError):
        onboard_seller(999_999_999, session=session)


def test_onboard_refuses_second_seller_for_same_user(session):
    user_id = insert_user(session, name="Фермер повторный онбординг")
    first = onboard_seller(user_id, session=session)

    with pytest.raises(SellerAlreadyExistsError) as exc:
        onboard_seller(user_id, session=session)

    assert exc.value.seller_id == first.seller_id


def test_onboard_does_not_issue_access_token(session):
    """Онбординг только подключает продавца. Токен он получает сам, обменяв
    код активации, — сервер не выдаёт рабочие учётные данные за него."""
    user_id = insert_user(session, name="Фермер без токена")

    result = onboard_seller(user_id, session=session)

    access_token = session.execute(
        text("SELECT access_token FROM Seller WHERE id = :id"), {"id": result.seller_id}
    ).scalar()
    assert access_token is None

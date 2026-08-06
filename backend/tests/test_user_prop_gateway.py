import pytest
from sqlalchemy import text

from app.platform.user_prop_gateway import UnknownPropError, UserPropGateway


@pytest.fixture
def user_id(session) -> int:
    return session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для свойств"}
    ).lastrowid


def test_read_returns_empty_dict_when_nothing_stored(session, user_id):
    gateway = UserPropGateway(session)
    assert gateway.read(user_id, ["gm_seller_row", "gm_seller_place"]) == {}


def test_write_then_read_varchar(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    assert gateway.read(user_id, ["gm_seller_row"]) == {"gm_seller_row": "Ряд 3"}


def test_write_then_read_text(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_short_description", "Фермерское хозяйство с 2015 года")
    assert gateway.read(user_id, ["gm_seller_short_description"]) == {
        "gm_seller_short_description": "Фермерское хозяйство с 2015 года"
    }


def test_write_overwrites_existing_value(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_place", "Место 1")
    gateway.write(user_id, "gm_seller_place", "Место 2")
    assert gateway.read(user_id, ["gm_seller_place"]) == {"gm_seller_place": "Место 2"}


def test_clear_removes_row_because_value_is_not_nullable(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_phone", "+79990000000")
    gateway.clear(user_id, "gm_seller_phone")
    assert gateway.read(user_id, ["gm_seller_phone"]) == {}


def test_read_mixes_varchar_and_text_props(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    gateway.write(user_id, "gm_seller_short_description", "Мёд и сыры")
    assert gateway.read(user_id, ["gm_seller_row", "gm_seller_short_description"]) == {
        "gm_seller_row": "Ряд 3",
        "gm_seller_short_description": "Мёд и сыры",
    }


def test_unknown_prop_var_raises(session, user_id):
    with pytest.raises(UnknownPropError):
        UserPropGateway(session).write(user_id, "gm_seller_nonexistent", "х")


def test_read_of_unknown_prop_var_raises(session, user_id):
    with pytest.raises(UnknownPropError):
        UserPropGateway(session).read(user_id, ["gm_seller_nonexistent"])


def test_platform_phone_returns_none_when_not_set(session, user_id):
    assert UserPropGateway(session).platform_phone(user_id) is None


def test_platform_phone_returns_digits_as_string(session, user_id):
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    assert UserPropGateway(session).platform_phone(user_id) == "79990000000"


def test_platform_phone_ignores_implausible_numbers(session, user_id):
    """На боевой платформе в users.phone встречаются значения длиной в одну
    цифру — подставлять такое продавцу как телефон нельзя."""
    session.execute(text("UPDATE users SET phone = 7 WHERE id_user = :id"), {"id": user_id})
    assert UserPropGateway(session).platform_phone(user_id) is None

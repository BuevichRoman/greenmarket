import pytest
from sqlalchemy import text

from app.platform.user_prop_gateway import (
    UnknownPropError,
    UnsupportedPropTypeError,
    UserPropGateway,
)


@pytest.fixture
def user_id(session) -> int:
    return session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для свойств"}
    ).lastrowid


@pytest.fixture
def other_user_id(session) -> int:
    return session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Другой продавец"}
    ).lastrowid


@pytest.fixture
def unsupported_prop_var(session) -> str:
    """Свойство с value_type = 3 (в платформенном словаре field_type тройка
    есть — это int). В platform_stub.sql его нет намеренно: стаб повторяет
    боевые данные, а такого свойства на проде не заведено. Строка откатится
    вместе с транзакцией фикстуры `session`."""
    var = "gm_seller_unsupported_type"
    session.execute(
        text("INSERT INTO users_prop (var, value_type) VALUES (:var, 3)"), {"var": var}
    )
    return var


def _raw_value(session, table: str, user_id: int, prop_var: str) -> str | None:
    """Значение напрямую из конкретной физической таблицы, в обход gateway —
    иначе тест не отличит varchar-таблицу от text-овой. Свойство и здесь
    резолвится по `var`, без хардкода id_users_prop."""
    row = session.execute(
        text(
            f"SELECT v.value FROM {table} v "
            "JOIN users_prop p ON p.id_users_prop = v.id_users_prop "
            "WHERE v.id_user = :user_id AND p.var = :prop_var"
        ),
        {"user_id": user_id, "prop_var": prop_var},
    ).first()
    return None if row is None else row[0]


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


def test_varchar_prop_lands_in_varchar_table(session, user_id):
    """Маппинг value_type → физическая таблица проверяется сырым SQL: если его
    перепутать, gateway останется внутренне согласованным (пишет и читает одну
    и ту же не ту таблицу), а на проде short_description упёрся бы в 255
    символов."""
    UserPropGateway(session).write(user_id, "gm_seller_row", "Ряд 3")
    assert _raw_value(session, "users_prop_items_varchar", user_id, "gm_seller_row") == "Ряд 3"
    assert _raw_value(session, "users_prop_items_text", user_id, "gm_seller_row") is None


def test_text_prop_lands_in_text_table(session, user_id):
    UserPropGateway(session).write(user_id, "gm_seller_short_description", "Мёд и сыры")
    assert (
        _raw_value(session, "users_prop_items_text", user_id, "gm_seller_short_description")
        == "Мёд и сыры"
    )
    assert (
        _raw_value(session, "users_prop_items_varchar", user_id, "gm_seller_short_description")
        is None
    )


def test_read_is_isolated_per_user(session, user_id, other_user_id):
    """GreenMarket живёт в одной схеме с пользователями чужой платформы —
    свойство одного продавца не должно протекать в профиль другого."""
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    gateway.write(other_user_id, "gm_seller_row", "Ряд 7")
    assert gateway.read(user_id, ["gm_seller_row"]) == {"gm_seller_row": "Ряд 3"}
    assert gateway.read(other_user_id, ["gm_seller_row"]) == {"gm_seller_row": "Ряд 7"}


def test_read_returns_only_filled_props(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    assert gateway.read(user_id, ["gm_seller_row", "gm_seller_place"]) == {"gm_seller_row": "Ряд 3"}


def test_read_without_props_returns_empty_dict(session, user_id):
    """Ранний выход из `_resolve` — оптимизация, а не защита: SQLAlchemy
    разворачивает пустой expanding IN в заведомо ложное условие, так что без
    guard'а поведение то же, просто ценой лишнего запроса. Тест фиксирует
    контракт метода, а не наличие guard'а."""
    assert UserPropGateway(session).read(user_id, []) == {}


def test_clear_removes_text_prop(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_short_description", "Мёд и сыры")
    gateway.clear(user_id, "gm_seller_short_description")
    assert gateway.read(user_id, ["gm_seller_short_description"]) == {}


def test_clear_of_empty_prop_is_not_an_error(session, user_id):
    UserPropGateway(session).clear(user_id, "gm_seller_place")


def test_write_of_unsupported_value_type_raises(session, user_id, unsupported_prop_var):
    with pytest.raises(UnsupportedPropTypeError) as exc_info:
        UserPropGateway(session).write(user_id, unsupported_prop_var, "х")
    assert unsupported_prop_var in str(exc_info.value)
    assert "3" in str(exc_info.value)


def test_read_of_unsupported_value_type_raises(session, user_id, unsupported_prop_var):
    with pytest.raises(UnsupportedPropTypeError):
        UserPropGateway(session).read(user_id, [unsupported_prop_var])


def test_clear_of_unsupported_value_type_raises(session, user_id, unsupported_prop_var):
    with pytest.raises(UnsupportedPropTypeError):
        UserPropGateway(session).clear(user_id, unsupported_prop_var)


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


def test_platform_phone_ignores_too_long_numbers(session, user_id):
    """Верхняя граница: колонка BIGINT, на проде встречаются 17-значные
    значения — телефоном это тоже не является."""
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 7999000000000000, "id": user_id},
    )
    assert UserPropGateway(session).platform_phone(user_id) is None

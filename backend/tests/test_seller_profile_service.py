import pytest
from sqlalchemy import text

from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.profile.errors import (
    ProfileValueTooLongError,
    SellerNotFoundError,
    UnknownMarketError,
    UnknownProfileFieldError,
)
from app.profile.seller_profile_service import SellerProfileService

# id, которого заведомо нет в Seller: таблица с AUTO_INCREMENT, до миллиарда
# строк в тестовой базе не доходит.
MISSING_SELLER_ID = 1_000_000_000


def create_seller(session, *, name: str) -> tuple[int, int]:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return seller_id, user_id


@pytest.fixture
def seller(session) -> tuple[int, int]:
    """Возвращает (seller_id, user_id) нового продавца."""
    return create_seller(session, name="Продавец для профиля")


def test_record_stores_author_and_role(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    repository.record(
        seller_id=seller_id,
        field="row",
        old_value=None,
        new_value="Ряд 3",
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()

    changes = repository.list_by_seller(seller_id)
    assert len(changes) == 1
    assert changes[0].field == "row"
    assert changes[0].old_value is None
    assert changes[0].new_value == "Ряд 3"
    assert changes[0].author_user_id == user_id
    assert changes[0].author_role == "SELLER"


def test_list_recent_returns_newest_first(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    for value in ("Ряд 1", "Ряд 2", "Ряд 3"):
        repository.record(
            seller_id=seller_id,
            field="row",
            old_value=None,
            new_value=value,
            author_user_id=user_id,
            author_role="ADMIN",
        )
    session.flush()

    recent = repository.list_recent(limit=2)
    assert [change.new_value for change in recent] == ["Ряд 3", "Ряд 2"]


def test_list_recent_respects_limit(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    for value in ("Ряд 1", "Ряд 2", "Ряд 3"):
        repository.record(
            seller_id=seller_id,
            field="row",
            old_value=None,
            new_value=value,
            author_user_id=user_id,
            author_role="ADMIN",
        )
    session.flush()

    assert len(repository.list_recent(limit=1)) == 1


def test_list_recent_covers_all_sellers(session):
    """Лента админа — глобальная: изменения разных продавцов в одном списке."""
    first_seller_id, first_user_id = create_seller(session, name="Первый продавец ленты")
    second_seller_id, second_user_id = create_seller(session, name="Второй продавец ленты")
    repository = SellerProfileChangeRepository(session)
    repository.record(
        seller_id=first_seller_id,
        field="row",
        old_value=None,
        new_value="Ряд первого",
        author_user_id=first_user_id,
        author_role="SELLER",
    )
    repository.record(
        seller_id=second_seller_id,
        field="place",
        old_value=None,
        new_value="Место второго",
        author_user_id=second_user_id,
        author_role="SELLER",
    )
    session.flush()

    recent = repository.list_recent(limit=2)
    assert {change.seller_id for change in recent} == {first_seller_id, second_seller_id}


def test_list_by_seller_does_not_leak_other_sellers(session):
    first_seller_id, first_user_id = create_seller(session, name="Продавец со своим журналом")
    second_seller_id, second_user_id = create_seller(session, name="Чужой продавец")
    repository = SellerProfileChangeRepository(session)
    repository.record(
        seller_id=first_seller_id,
        field="row",
        old_value=None,
        new_value="Ряд свой",
        author_user_id=first_user_id,
        author_role="SELLER",
    )
    repository.record(
        seller_id=second_seller_id,
        field="row",
        old_value=None,
        new_value="Ряд чужой",
        author_user_id=second_user_id,
        author_role="SELLER",
    )
    session.flush()

    changes = repository.list_by_seller(first_seller_id)
    assert [change.new_value for change in changes] == ["Ряд свой"]


def test_read_returns_all_fields_as_none_for_empty_profile(session, seller):
    seller_id, _ = seller
    profile = SellerProfileService(session).read(seller_id)
    assert profile == {
        "row": None,
        "place": None,
        "working_hours": None,
        "short_description": None,
        "phone": None,
        "whatsapp": None,
        "market_id": None,
    }


def test_apply_writes_values_and_journal(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)

    changed = service.apply(
        seller_id,
        {"row": "Ряд 3", "phone": "+79990000000"},
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()

    assert changed == ["row", "phone"]
    profile = service.read(seller_id)
    assert profile["row"] == "Ряд 3"
    assert profile["phone"] == "+79990000000"

    journal = SellerProfileChangeRepository(session).list_by_seller(seller_id)
    assert {(change.field, change.old_value, change.new_value) for change in journal} == {
        ("row", None, "Ряд 3"),
        ("phone", None, "+79990000000"),
    }


def test_apply_records_old_value_on_overwrite(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"place": "Место 1"}, author_user_id=user_id, author_role="SELLER")
    service.apply(seller_id, {"place": "Место 2"}, author_user_id=user_id, author_role="ADMIN")
    session.flush()

    latest = SellerProfileChangeRepository(session).list_by_seller(seller_id)[0]
    assert (latest.field, latest.old_value, latest.new_value) == ("place", "Место 1", "Место 2")
    assert latest.author_role == "ADMIN"


def test_apply_ignores_unchanged_values(session, seller):
    """Сохранение формы без правок не должно засорять ленту админа."""
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"row": "Ряд 3"}, author_user_id=user_id, author_role="SELLER")
    changed = service.apply(seller_id, {"row": "Ряд 3"}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert changed == []
    assert len(SellerProfileChangeRepository(session).list_by_seller(seller_id)) == 1


def test_apply_clears_field_on_empty_string(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"working_hours": "9:00–18:00"}, author_user_id=user_id, author_role="SELLER")
    service.apply(seller_id, {"working_hours": ""}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert service.read(seller_id)["working_hours"] is None
    latest = SellerProfileChangeRepository(session).list_by_seller(seller_id)[0]
    assert (latest.old_value, latest.new_value) == ("9:00–18:00", None)


def test_apply_strips_whitespace(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"row": "  Ряд 3  "}, author_user_id=user_id, author_role="SELLER")
    session.flush()
    assert service.read(seller_id)["row"] == "Ряд 3"


def test_apply_rejects_unknown_field(session, seller):
    seller_id, user_id = seller
    with pytest.raises(UnknownProfileFieldError):
        SellerProfileService(session).apply(
            seller_id, {"id_role": "4"}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_rejects_too_long_value(session, seller):
    seller_id, user_id = seller
    with pytest.raises(ProfileValueTooLongError):
        SellerProfileService(session).apply(
            seller_id, {"row": "х" * 256}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_rejects_too_long_short_description(session, seller):
    """Ограничение 2000 — продуктовое: колонка users_prop_items_text.value держит
    65535 символов, поэтому без проверки в сервисе оно не работает вообще."""
    seller_id, user_id = seller
    with pytest.raises(ProfileValueTooLongError):
        SellerProfileService(session).apply(
            seller_id, {"short_description": "х" * 2001}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_accepts_values_of_exactly_max_length(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(
        seller_id,
        {"row": "х" * 255, "short_description": "х" * 2000},
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()

    profile = service.read(seller_id)
    assert profile["row"] == "х" * 255
    assert profile["short_description"] == "х" * 2000


def test_apply_does_not_touch_other_sellers_profile(session):
    first_seller_id, first_user_id = create_seller(session, name="Продавец со своим профилем")
    second_seller_id, second_user_id = create_seller(session, name="Чужой продавец профиля")
    service = SellerProfileService(session)
    service.apply(first_seller_id, {"row": "Ряд свой"}, author_user_id=first_user_id, author_role="SELLER")
    service.apply(second_seller_id, {"row": "Ряд чужой"}, author_user_id=second_user_id, author_role="SELLER")
    session.flush()

    assert service.read(first_seller_id)["row"] == "Ряд свой"
    assert service.read(second_seller_id)["row"] == "Ряд чужой"


def test_apply_writes_nothing_when_a_value_is_too_long(session, seller):
    """Проверка длины должна пройти по всем полям до первой записи — иначе часть
    формы сохранится, а часть нет, и продавец об этом не узнает."""
    seller_id, user_id = seller
    service = SellerProfileService(session)
    with pytest.raises(ProfileValueTooLongError):
        service.apply(
            seller_id,
            {"row": "Ряд 3", "short_description": "х" * 2001},
            author_user_id=user_id,
            author_role="SELLER",
        )

    assert service.read(seller_id)["row"] is None
    assert SellerProfileChangeRepository(session).list_by_seller(seller_id) == []


def test_read_suggests_platform_phone_when_own_is_empty(session, seller):
    seller_id, user_id = seller
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    assert SellerProfileService(session).read(seller_id)["phone"] is None
    assert SellerProfileService(session).suggested_phone(seller_id) == "79990000000"


def test_suggested_phone_is_none_when_own_value_exists(session, seller):
    seller_id, user_id = seller
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    SellerProfileService(session).apply(
        seller_id, {"phone": "+79991112233"}, author_user_id=user_id, author_role="SELLER"
    )
    session.flush()
    assert SellerProfileService(session).suggested_phone(seller_id) is None


def test_apply_leaves_fields_absent_from_request_untouched(session, seller):
    """Отсутствие ключа — «не редактировали», а не «очистить».

    Эндпоинт кормит сюда `exclude_unset`, поэтому форма, приславшая один
    телефон, не должна стереть ряд, место, часы, описание и WhatsApp — и
    отчитаться о пяти изменениях в ленте админа.
    """
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"row": "Ряд 3"}, author_user_id=user_id, author_role="SELLER")
    changed = service.apply(seller_id, {"place": "Место 1"}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert changed == ["place"]
    profile = service.read(seller_id)
    assert profile["row"] == "Ряд 3"
    assert profile["place"] == "Место 1"
    assert len(SellerProfileChangeRepository(session).list_by_seller(seller_id)) == 2


def test_apply_records_the_caller_as_author_not_the_seller(session, seller):
    """Админ, правящий чужой профиль, должен быть отличим от самого продавца —
    ради этого журнал и заведён."""
    seller_id, seller_user_id = seller
    admin_user_id = session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Администратор профиля"}
    ).lastrowid

    SellerProfileService(session).apply(
        seller_id, {"row": "Ряд от админа"}, author_user_id=admin_user_id, author_role="ADMIN"
    )
    session.flush()

    latest = SellerProfileChangeRepository(session).list_by_seller(seller_id)[0]
    assert latest.author_user_id == admin_user_id
    assert latest.author_user_id != seller_user_id
    assert latest.author_role == "ADMIN"


def test_read_returns_empty_profile_for_missing_seller(session):
    """Мягкое поведение намеренное: 404 отдаёт эндпоинт, проверив продавца сам."""
    assert SellerProfileService(session).read(MISSING_SELLER_ID) == {
        "row": None,
        "place": None,
        "working_hours": None,
        "short_description": None,
        "phone": None,
        "whatsapp": None,
        "market_id": None,
    }


def insert_market(session, *, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Market (name, address, is_active) VALUES (:name, 'Москва, Тестовая, 1', :is_active)"),
        {"name": name, "is_active": is_active},
    ).lastrowid


def test_apply_stores_market_id(session, seller):
    seller_id, user_id = seller
    market_id = insert_market(session, name="Рынок для профиля")
    service = SellerProfileService(session)

    changed = service.apply(
        seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER"
    )
    session.flush()

    assert changed == ["market_id"]
    assert service.read(seller_id)["market_id"] == str(market_id)


def test_apply_rejects_unknown_market(session, seller):
    """Внешнего ключа из users_prop в Market быть не может — проверять
    существование рынка обязан сервис, иначе профиль сошлётся в пустоту."""
    seller_id, user_id = seller

    with pytest.raises(UnknownMarketError):
        SellerProfileService(session).apply(
            seller_id, {"market_id": "999999"}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_rejects_inactive_market(session, seller):
    seller_id, user_id = seller
    market_id = insert_market(session, name="Закрытый рынок для профиля", is_active=False)

    with pytest.raises(UnknownMarketError):
        SellerProfileService(session).apply(
            seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_rejects_non_numeric_market_id(session, seller):
    seller_id, user_id = seller

    with pytest.raises(UnknownMarketError):
        SellerProfileService(session).apply(
            seller_id, {"market_id": "Даниловский"}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_allows_clearing_market(session, seller):
    seller_id, user_id = seller
    market_id = insert_market(session, name="Рынок, который покинут")
    service = SellerProfileService(session)
    service.apply(seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER")

    changed = service.apply(seller_id, {"market_id": None}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert changed == ["market_id"]
    assert service.read(seller_id)["market_id"] is None


def test_apply_rejects_missing_seller(session, seller):
    _, user_id = seller
    with pytest.raises(SellerNotFoundError):
        SellerProfileService(session).apply(
            MISSING_SELLER_ID, {"row": "Ряд 3"}, author_user_id=user_id, author_role="ADMIN"
        )


def test_changed_order_does_not_depend_on_request_order(session, seller):
    """Порядок ответа задаёт PROFILE_FIELDS, а не то, как клиент собрал JSON."""
    seller_id, user_id = seller
    changed = SellerProfileService(session).apply(
        seller_id,
        {"whatsapp": "+79990000001", "row": "Ряд 3", "place": "Место 1"},
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()
    assert changed == ["row", "place", "whatsapp"]

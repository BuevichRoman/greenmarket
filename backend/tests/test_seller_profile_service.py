import pytest
from sqlalchemy import text

from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)


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

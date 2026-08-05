from sqlalchemy import text

from app.publication.seller_access import resolve_seller_access


def insert_seller(session, *, name: str, access_token: str | None = None) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    seller_id = session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid
    if access_token is not None:
        session.execute(
            text("UPDATE Seller SET access_token = :token, is_active = TRUE WHERE id = :id"),
            {"token": access_token, "id": seller_id},
        )
    return seller_id


def test_valid_token_resolves_to_seller_access(session):
    seller_id = insert_seller(session, name="Ферма Ромашково", access_token="tok-abc")

    access = resolve_seller_access("tok-abc", session)

    assert access is not None
    assert access.seller_id == seller_id
    assert access.name == "Ферма Ромашково"


def test_unknown_token_resolves_to_none(session):
    insert_seller(session, name="Ферма Ромашково", access_token="tok-abc")

    assert resolve_seller_access("tok-does-not-exist", session) is None


def test_deactivated_seller_still_resolves(session):
    """Временная деактивация скрывает каталог от покупателей, но не отключает
    самого продавца: он продолжает работать в кабинете и публиковать
    (решение коллеги от 2026-08-05, Admin_MVP.md «Временная деактивация»).
    Видимость покупателю фильтруется отдельно — SellerGateway.list_active_seller_ids.
    """
    seller_id = insert_seller(session, name="Деактивированная ферма", access_token="tok-inactive")
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    access = resolve_seller_access("tok-inactive", session)

    assert access is not None
    assert access.seller_id == seller_id

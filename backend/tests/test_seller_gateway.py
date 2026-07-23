from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.platform.seller_gateway import SellerGateway


def insert_seller(session, *, name: str, publication_key: str | None, catalog_hash: str | None) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    result = session.execute(
        text(
            "INSERT INTO Seller (user_id, current_publication_key, current_catalog_hash) "
            "VALUES (:user_id, :publication_key, :catalog_hash)"
        ),
        {"user_id": user_id, "publication_key": publication_key, "catalog_hash": catalog_hash},
    )
    return result.lastrowid


def test_returns_current_publication_key_for_published_seller(session):
    seller_id = insert_seller(session, name="Фермер Иванов", publication_key="key-123", catalog_hash="hash-abc")

    assert SellerGateway(session).get_current_publication_key(seller_id) == "key-123"


def test_returns_current_catalog_hash_for_published_seller(session):
    seller_id = insert_seller(session, name="Фермер Петров", publication_key="key-456", catalog_hash="hash-def")

    assert SellerGateway(session).get_current_catalog_hash(seller_id) == "hash-def"


def test_returns_none_when_seller_never_published(session):
    seller_id = insert_seller(session, name="Новый продавец", publication_key=None, catalog_hash=None)

    gateway = SellerGateway(session)
    assert gateway.get_current_publication_key(seller_id) is None
    assert gateway.get_current_catalog_hash(seller_id) is None


def test_returns_none_for_missing_seller(session):
    gateway = SellerGateway(session)
    assert gateway.get_current_publication_key(999_999) is None
    assert gateway.get_current_catalog_hash(999_999) is None


def test_update_current_publication_overwrites_key_hash_and_version(session):
    seller_id = insert_seller(session, name="Продавец для обновления", publication_key="old-key", catalog_hash="old-hash")
    gateway = SellerGateway(session)

    gateway.update_current_publication(seller_id, publication_key="new-key", catalog_hash="new-hash", catalog_version=3)

    assert gateway.get_current_publication_key(seller_id) == "new-key"
    assert gateway.get_current_catalog_hash(seller_id) == "new-hash"
    version = session.execute(
        text("SELECT current_catalog_version FROM Seller WHERE id = :seller_id"), {"seller_id": seller_id}
    ).scalar()
    assert version == 3


def test_list_active_seller_ids_returns_only_active(session):
    active_id = insert_seller(session, name="Активный продавец", publication_key=None, catalog_hash=None)
    session.execute(text("UPDATE Seller SET is_active = TRUE WHERE id = :id"), {"id": active_id})
    inactive_id = insert_seller(session, name="Неактивный продавец", publication_key=None, catalog_hash=None)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": inactive_id})

    result = SellerGateway(session).list_active_seller_ids([active_id, inactive_id])

    assert result == {active_id}


def test_list_active_seller_ids_returns_empty_set_for_empty_input(session):
    assert SellerGateway(session).list_active_seller_ids([]) == set()


def test_list_active_seller_ids_ignores_unknown_ids(session):
    active_id = insert_seller(session, name="Продавец для проверки unknown", publication_key=None, catalog_hash=None)

    result = SellerGateway(session).list_active_seller_ids([active_id, 999_999])

    assert result == {active_id}


def test_get_status_returns_active_flag_and_version(session):
    seller_id = insert_seller(session, name="Продавец статус", publication_key="key", catalog_hash="hash")
    session.execute(
        text("UPDATE Seller SET is_active = TRUE, current_catalog_version = 3 WHERE id = :id"), {"id": seller_id}
    )

    status = SellerGateway(session).get_status(seller_id)

    assert status.is_active is True
    assert status.current_catalog_version == 3


def test_get_status_defaults_version_to_zero_when_never_published(session):
    seller_id = insert_seller(session, name="Продавец без публикаций для статуса", publication_key=None, catalog_hash=None)

    status = SellerGateway(session).get_status(seller_id)

    assert status.current_catalog_version == 0


def test_get_status_returns_none_for_missing_seller(session):
    assert SellerGateway(session).get_status(999_999) is None


def test_get_status_returns_false_for_inactive_seller(session):
    seller_id = insert_seller(session, name="Продавец неактивен для статуса", publication_key=None, catalog_hash=None)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    status = SellerGateway(session).get_status(seller_id)

    assert status.is_active is False


def test_set_activation_code_and_find_by_activation_code(session):
    seller_id = insert_seller(session, name="Продавец для кода активации", publication_key=None, catalog_hash=None)
    # microsecond=0: колонка activation_code_expires_at — DATETIME без долей секунды (миграция 011),
    # MySQL обрежет микросекунды при сохранении, так что сравнивать нужно без них
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(days=7)
    gateway = SellerGateway(session)

    gateway.set_activation_code(seller_id, activation_code="abc12345", expires_at=expires_at)
    lookup = gateway.find_by_activation_code("abc12345")

    assert lookup is not None
    assert lookup.seller_id == seller_id
    assert lookup.activation_code_expires_at == expires_at


def test_find_by_activation_code_returns_none_for_unknown_code(session):
    assert SellerGateway(session).find_by_activation_code("does-not-exist") is None


def test_set_access_token_clears_activation_code_and_sets_fields(session):
    seller_id = insert_seller(session, name="Продавец для access_token", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_activation_code(
        seller_id, activation_code="code-1", expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    )

    gateway.set_access_token(seller_id, access_token="tok-xyz", spreadsheet_id="sheet-abc")

    assert gateway.find_by_activation_code("code-1") is None  # код одноразовый, обнулён
    access = gateway.find_by_access_token("tok-xyz")
    assert access is not None
    assert access.seller_id == seller_id


def test_find_by_access_token_returns_none_for_unknown_token(session):
    assert SellerGateway(session).find_by_access_token("does-not-exist") is None


def test_find_by_access_token_returns_none_for_inactive_seller(session):
    seller_id = insert_seller(session, name="Неактивный продавец с токеном", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_access_token(seller_id, access_token="tok-inactive", spreadsheet_id="sheet-x")
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    assert gateway.find_by_access_token("tok-inactive") is None


def test_find_by_access_token_returns_seller_name_from_users(session):
    seller_id = insert_seller(session, name="Ферма Токеновая", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_access_token(seller_id, access_token="tok-name", spreadsheet_id="sheet-n")

    access = gateway.find_by_access_token("tok-name")

    assert access.name == "Ферма Токеновая"

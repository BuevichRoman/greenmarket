from decimal import Decimal

from sqlalchemy import text

from app.infrastructure.repositories.market_repository import MarketRepository


def insert_market(session, *, name: str, address: str = "Москва, ул. Тестовая, 1", is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Market (name, address, is_active) VALUES (:name, :address, :is_active)"),
        {"name": name, "address": address, "is_active": is_active},
    ).lastrowid


def test_find_by_id_returns_market(session):
    market_id = insert_market(session, name="Даниловский рынок")

    market = MarketRepository(session).find_by_id(market_id)

    assert market is not None
    assert market.name == "Даниловский рынок"


def test_find_by_id_returns_none_for_missing_market(session):
    assert MarketRepository(session).find_by_id(999_999) is None


def test_list_active_excludes_inactive_markets(session):
    active_id = insert_market(session, name="Активный рынок для list_active")
    inactive_id = insert_market(session, name="Закрытый рынок для list_active", is_active=False)

    ids = [m.id for m in MarketRepository(session).list_active()]

    assert active_id in ids
    assert inactive_id not in ids


def test_list_all_includes_inactive_markets(session):
    """Админу нужен и закрытый рынок — иначе его нельзя вернуть в работу."""
    inactive_id = insert_market(session, name="Закрытый рынок для list_all", is_active=False)

    ids = [m.id for m in MarketRepository(session).list_all()]

    assert inactive_id in ids


def test_create_stores_coordinates(session):
    repository = MarketRepository(session)

    market = repository.create(
        name="Рынок с координатами",
        address="Москва, Мытная, 74",
        latitude=Decimal("55.7150000"),
        longitude=Decimal("37.6210000"),
    )

    saved = repository.find_by_id(market.id)
    assert (saved.latitude, saved.longitude) == (Decimal("55.7150000"), Decimal("37.6210000"))
    assert saved.is_active is True


def test_create_allows_market_without_coordinates(session):
    """Точка заводится по названию и адресу — координаты можно снять позже."""
    market = MarketRepository(session).create(name="Рынок без точки", address="Москва, Тестовая, 2")

    assert market.latitude is None
    assert market.longitude is None


def test_create_defaults_to_market_type(session):
    """Умолчание — рынок: лавка это частный случай, который указывают явно."""
    market = MarketRepository(session).create(name="Точка без типа", address="Москва, Тестовая, 6")

    assert market.type == "MARKET"


def test_create_stores_shop_type(session):
    """Лавка — отдельно стоящая точка в городе или деревне (Валентин, 10.08)."""
    shop = MarketRepository(session).create(name="Лавка у дома", address="Казань, Баумана, 5", type="SHOP")

    assert MarketRepository(session).find_by_id(shop.id).type == "SHOP"

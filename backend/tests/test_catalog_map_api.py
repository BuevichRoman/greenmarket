"""Публичный API карты (Валентин, 10.08.2026: карту доделывает заместитель).

Карте нужен не один продавец по id, а все точки сразу и продавцы внутри
выбранной точки. Правило видимости то же, что во всём Catalog API: покупателю
существует только активный продавец с опубликованными товарами — пустой пин на
карте хуже отсутствующего.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app
from app.profile.seller_profile_service import SellerProfileService


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_market(session, *, name: str, type: str = "MARKET", is_active: bool = True) -> int:
    return session.execute(
        text(
            "INSERT INTO Market (name, type, address, latitude, longitude, is_active) "
            "VALUES (:name, :type, 'Казань, Баумана, 5', 55.7900000, 49.1200000, :is_active)"
        ),
        {"name": name, "type": type, "is_active": is_active},
    ).lastrowid


def insert_seller(session, *, name: str, is_active: bool = True) -> tuple[int, int]:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id, is_active) VALUES (:user_id, :is_active)"),
        {"user_id": user_id, "is_active": is_active},
    ).lastrowid
    return seller_id, user_id


def attach_to_market(session, seller_id: int, user_id: int, market_id: int) -> None:
    SellerProfileService(session).apply(
        seller_id, {"market_id": str(market_id)}, author_user_id=user_id, author_role="SELLER"
    )


def publish_product(session, seller_id: int, *, name: str) -> None:
    group_id = session.execute(
        text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": f"Группа {name}"}
    ).lastrowid
    product_id = session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid
    session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit, is_published) "
            "VALUES (:seller_id, :product_id, :name, 100, 'кг', TRUE)"
        ),
        {"seller_id": seller_id, "product_id": product_id, "name": name},
    )


def test_lists_market_with_seller_count(committing_session):
    market_id = insert_market(committing_session, name="Рынок на карте")
    seller_id, user_id = insert_seller(committing_session, name="Продавец на карте")
    attach_to_market(committing_session, seller_id, user_id, market_id)
    publish_product(committing_session, seller_id, name="Товар на карте")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/markets")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    market = next(m for m in response.json()["markets"] if m["id"] == market_id)
    assert market["name"] == "Рынок на карте"
    assert market["type"] == "MARKET"
    assert (market["latitude"], market["longitude"]) == ("55.7900000", "49.1200000")
    assert market["seller_count"] == 1


def test_hides_market_without_visible_sellers(committing_session):
    """Пин, за которым покупателю ничего нет, — это обманутое ожидание."""
    market_id = insert_market(committing_session, name="Рынок без продавцов")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/markets")

    app.dependency_overrides.clear()
    assert all(m["id"] != market_id for m in response.json()["markets"])


def test_hides_market_without_coordinates(committing_session):
    """На карту точку без координат поставить нечем."""
    market_id = committing_session.execute(
        text("INSERT INTO Market (name, address, is_active) VALUES ('Точка без координат', 'Казань', TRUE)")
    ).lastrowid
    seller_id, user_id = insert_seller(committing_session, name="Продавец без координат")
    attach_to_market(committing_session, seller_id, user_id, market_id)
    publish_product(committing_session, seller_id, name="Товар без координат")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/markets")

    app.dependency_overrides.clear()
    assert all(m["id"] != market_id for m in response.json()["markets"])


def test_seller_count_ignores_inactive_seller(committing_session):
    market_id = insert_market(committing_session, name="Рынок с выключенным продавцом")
    visible_id, visible_user = insert_seller(committing_session, name="Видимый продавец")
    hidden_id, hidden_user = insert_seller(committing_session, name="Выключенный продавец", is_active=False)
    attach_to_market(committing_session, visible_id, visible_user, market_id)
    attach_to_market(committing_session, hidden_id, hidden_user, market_id)
    publish_product(committing_session, visible_id, name="Видимый товар")
    publish_product(committing_session, hidden_id, name="Скрытый товар")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/markets")

    app.dependency_overrides.clear()
    market = next(m for m in response.json()["markets"] if m["id"] == market_id)
    assert market["seller_count"] == 1


def test_lists_sellers_of_a_market(committing_session):
    market_id = insert_market(committing_session, name="Рынок со списком продавцов")
    seller_id, user_id = insert_seller(committing_session, name="Пасека Ромашково")
    attach_to_market(committing_session, seller_id, user_id, market_id)
    SellerProfileService(committing_session).apply(
        seller_id, {"row": "Ряд 3", "place": "Место 12"}, author_user_id=user_id, author_role="SELLER"
    )
    publish_product(committing_session, seller_id, name="Мёд гречишный")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/markets/{market_id}/sellers")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    sellers = response.json()["sellers"]
    assert [s["seller_id"] for s in sellers] == [seller_id]
    assert sellers[0]["name"] == "Пасека Ромашково"
    assert (sellers[0]["row"], sellers[0]["place"]) == ("Ряд 3", "Место 12")
    assert sellers[0]["product_count"] == 1


def test_sellers_of_missing_market_report_404(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/markets/999999/sellers")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_closed_market_is_not_shown(committing_session):
    # Рынок закрывается уже после привязки: выбрать закрытый продавец не может
    # (SellerProfileService этого не даст), а вот закрыть работающий — обычное
    # дело, и уже привязанные к нему продавцы должны исчезнуть с карты.
    market_id = insert_market(committing_session, name="Закрытый рынок")
    seller_id, user_id = insert_seller(committing_session, name="Продавец закрытого рынка")
    attach_to_market(committing_session, seller_id, user_id, market_id)
    publish_product(committing_session, seller_id, name="Товар закрытого рынка")
    committing_session.execute(
        text("UPDATE Market SET is_active = FALSE WHERE id = :id"), {"id": market_id}
    )
    override_session(committing_session)
    client = TestClient(app)

    listed = client.get("/api/v1/catalog/markets")
    sellers = client.get(f"/api/v1/catalog/markets/{market_id}/sellers")

    app.dependency_overrides.clear()
    assert all(m["id"] != market_id for m in listed.json()["markets"])
    assert sellers.status_code == 404

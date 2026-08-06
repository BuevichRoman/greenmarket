from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.publications import get_seller_access_resolver
from app.infrastructure.database import get_session
from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.main import app
from app.publication.seller_access import SellerAccess

VALID_TOKEN = "seller-profile-test-token"


def override_seller_access(seller_id: int, published_by: int) -> None:
    # published_by — это и есть платформенный users.id_user продавца
    # (см. app/publication/seller_access.py): поле названо по первому
    # потребителю, публикации, но хранит именно id пользователя.
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name="Пасека Ромашково")
    app.dependency_overrides[get_seller_access_resolver] = lambda: (
        lambda token: access if token == VALID_TOKEN else None
    )


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str, phone: int | None = None) -> tuple[int, int]:
    user_id = session.execute(
        text("INSERT INTO users (name, phone) VALUES (:name, :phone)"), {"name": name, "phone": phone}
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return seller_id, user_id


def setup_client(committing_session, *, phone: int | None = None) -> tuple[TestClient, int]:
    seller_id, user_id = insert_seller(committing_session, name="Пасека Ромашково", phone=phone)
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    return TestClient(app), seller_id


def test_get_profile_returns_empty_fields_for_new_seller(committing_session):
    client, seller_id = setup_client(committing_session)

    response = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["name"] == "Пасека Ромашково"
    assert body["status"] == "ACTIVE"
    assert body["row"] is None
    assert body["phone"] is None
    assert body["suggested_phone"] is None


def test_get_profile_rejects_bad_token(committing_session):
    client, _ = setup_client(committing_session)

    response = client.get("/api/v1/seller/profile", params={"access_token": "nope"})

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_get_profile_returns_404_for_token_with_no_seller_row(committing_session):
    # Токен резолвится (не 403), но указывает на несуществующий seller_id:
    # это «продавец не найден», а не проблема доступа. Сам сервис на такого
    # продавца ошибку не бросает — читается профиль сплошь из None, — поэтому
    # 404 отдаёт именно эндпоинт, и проверять его нужно здесь.
    override_session(committing_session)
    override_seller_access(999_999, 1)
    client = TestClient(app)

    response = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_put_profile_saves_and_returns_changed_fields(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put(
        "/api/v1/seller/profile",
        json={"access_token": VALID_TOKEN, "row": "Ряд 3", "place": "Место 12"},
    )
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert sorted(response.json()["changed"]) == ["place", "row"]
    assert saved["row"] == "Ряд 3"
    assert saved["place"] == "Место 12"


def test_put_profile_leaves_omitted_fields_untouched(committing_session):
    client, _ = setup_client(committing_session)

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "place": "Место 12"})
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert saved["row"] == "Ряд 3"
    assert saved["place"] == "Место 12"


def test_put_profile_rejects_bad_token(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put("/api/v1/seller/profile", json={"access_token": "nope", "row": "Ряд 3"})

    app.dependency_overrides.clear()
    assert response.status_code == 403


def test_put_profile_rejects_too_long_value(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put(
        "/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "х" * 256}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_profile_suggests_platform_phone(committing_session):
    client, _ = setup_client(committing_session, phone=79990000000)

    body = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert body["phone"] is None
    assert body["suggested_phone"] == "79990000000"


def test_put_profile_clears_field_with_empty_string(committing_session):
    # Заявленная семантика контракта: отсутствие ключа — «не трогать»,
    # пустая строка — «очистить». Через HTTP проверяется только здесь.
    client, _ = setup_client(committing_session)

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    response = client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": ""})
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["changed"] == ["row"]
    assert saved["row"] is None


def test_put_profile_rejects_unknown_field(committing_session):
    # Единственный клиент эндпоинта — форма в книге продавца, где имена полей
    # набиты руками. Опечатка в имени поля должна быть слышна сразу, а не
    # выглядеть как успешное сохранение с пустым changed.
    client, _ = setup_client(committing_session)

    response = client.put(
        "/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "id_role": "4"}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_profile_drops_suggestion_once_own_phone_saved(committing_session):
    client, _ = setup_client(committing_session, phone=79990000000)

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "phone": "79991112233"})
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert saved["phone"] == "79991112233"
    assert saved["suggested_phone"] is None


def test_put_profile_without_changes_returns_empty_changed(committing_session):
    client, _ = setup_client(committing_session)

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    response = client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["changed"] == []


def test_put_profile_survives_rollback_of_later_work(committing_session):
    # Все прочие тесты видят запись PUT просто потому, что делят с ним сессию, —
    # без коммита они бы тоже прошли. Откат после запроса отделяет «записано в
    # сессию» от «зафиксировано»: если эндпоинт забудет session.commit(),
    # сохранённое значение исчезнет.
    client, _ = setup_client(committing_session)
    # Продавца фиксируем до PUT, иначе откат снёс бы и его: тогда GET отдал бы
    # 404, и тест падал бы на отсутствии продавца, а не на пустом профиле —
    # то есть проверял бы «ничего не зафиксировалось» вместо «не
    # зафиксировалась именно запись профиля».
    committing_session.commit()

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    committing_session.rollback()
    response = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["row"] == "Ряд 3"


def test_put_profile_records_seller_as_author_in_journal(committing_session):
    # Продавец правит свой профиль сам — в журнале должна быть роль SELLER и
    # его собственный платформенный id_user, иначе лента админа не различит,
    # кто именно менял поле.
    client, seller_id = setup_client(committing_session)
    user_id = committing_session.execute(
        text("SELECT user_id FROM Seller WHERE id = :id"), {"id": seller_id}
    ).scalar_one()

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    changes = SellerProfileChangeRepository(committing_session).list_by_seller(seller_id)

    app.dependency_overrides.clear()
    assert [(change.field, change.author_role, change.author_user_id) for change in changes] == [
        ("row", "SELLER", user_id)
    ]

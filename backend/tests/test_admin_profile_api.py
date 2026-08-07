from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin.admin_activation import issue_admin_activation_code
from app.api.v1.admin_schemas import (
    AdminSellerProfileResponse,
    AdminSellerProfileUpdateRequest,
)
from app.infrastructure.database import get_session
from app.main import app
from app.profile.fields import PROFILE_FIELDS
from app.profile.seller_profile_service import SellerProfileService


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_seller(session, *, name: str) -> tuple[int, int]:
    user_id = insert_user(session, name=name)
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return seller_id, user_id


def admin_headers(session, client, *, name: str) -> tuple[dict[str, str], int]:
    """Настоящий админский токен, а не подмена get_admin_access: подмена скрыла
    бы и разбор заголовка, и то, чей именно user_id доезжает до журнала."""
    # Журнал пишет платформенный users.id_user, а не Administrator.id, и
    # отличить одно от другого тест может только если значения разные. На
    # свежей базе (platform_stub.sql не сидит ни одного пользователя) оба
    # счётчика стартуют с единицы, и у первого же администратора id совпал бы
    # с user_id — подмена одного другим тогда не ловится ничем. Лишняя строка
    # в users уводит счётчики врозь по построению, а не по везению.
    insert_user(session, name=f"{name} (сдвиг счётчика users)")
    user_id = insert_user(session, name=name)
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def test_admin_updates_seller_profile(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ профиля")
    seller_id, _ = insert_seller(committing_session, name="Пасека Ромашково")

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile",
        json={"row": "Ряд 3", "place": "Место 12"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert sorted(body["changed"]) == ["place", "row"]
    assert SellerProfileService(committing_session).read(seller_id)["row"] == "Ряд 3"


def test_admin_update_rejects_unknown_seller(committing_session):
    # В отличие от продавцовской половины seller_id приходит из пути, а не из
    # токена: несуществующий продавец — обычная опечатка админа, а не
    # недостижимая ветка.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ несуществующего профиля")

    response = client.put(
        "/api/v1/admin/sellers/999999/profile", json={"row": "Ряд 3"}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_admin_update_rejects_too_long_value(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ длинного значения")
    seller_id, _ = insert_seller(committing_session, name="Пасека длинного значения")

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "х" * 256}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_update_rejects_unknown_field(committing_session):
    # Опечатка в имени поля не должна выглядеть как успешное сохранение с
    # пустым changed — иначе один и тот же сервис отвечал бы продавцу 422, а
    # администратору 200.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ неизвестного поля")
    seller_id, _ = insert_seller(committing_session, name="Пасека неизвестного поля")

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile", json={"id_role": "4"}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_update_commits_the_change(committing_session):
    # Остальные тесты видят запись просто потому, что делят сессию с запросом:
    # без commit() они бы тоже прошли. Откат внешней транзакции отделяет
    # «записано в сессию» от «зафиксировано».
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ коммита")
    seller_id, _ = insert_seller(committing_session, name="Пасека коммита")
    # Продавца и админа фиксируем до PUT: иначе откат снёс бы и их, и тест
    # падал бы на отсутствии продавца, а не на незафиксированной правке.
    committing_session.commit()

    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"}, headers=headers)
    committing_session.rollback()
    feed = client.get("/api/v1/admin/profile-changes", headers=headers).json()

    app.dependency_overrides.clear()
    assert SellerProfileService(committing_session).read(seller_id)["row"] == "Ряд 3"
    assert [c for c in feed["changes"] if c["seller_id"] == seller_id] != []


def test_feed_shows_admin_as_author(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, admin_user_id = admin_headers(committing_session, client, name="Админ ленты")
    seller_id, _ = insert_seller(committing_session, name="Пасека ленты")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 7"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    changes = [c for c in response.json()["changes"] if c["seller_id"] == seller_id]
    assert len(changes) == 1
    change = changes[0]
    assert change["field"] == "row"
    assert change["old_value"] is None
    assert change["new_value"] == "Ряд 7"
    assert change["author_role"] == "ADMIN"
    assert change["author_user_id"] == admin_user_id
    assert change["seller_name"] == "Пасека ленты"
    assert change["created_at"] is not None


def test_feed_is_newest_first(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ порядка")
    seller_id, _ = insert_seller(committing_session, name="Пасека порядка")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"place": "Место 2"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"phone": "79990000000"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", headers=headers)

    app.dependency_overrides.clear()
    changes = [c for c in response.json()["changes"] if c["seller_id"] == seller_id]
    assert [c["field"] for c in changes] == ["phone", "place", "row"]


def test_feed_respects_limit(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ лимита")
    seller_id, _ = insert_seller(committing_session, name="Пасека лимита")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"place": "Место 2"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"phone": "79990000000"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", params={"limit": 2}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    changes = response.json()["changes"]
    assert len(changes) == 2
    # Обрезаются старые, а не новые.
    assert [c["field"] for c in changes] == ["phone", "place"]


def test_feed_is_global_across_sellers(committing_session):
    # Лента админская, а не продавцовская: администратор смотрит одну общую
    # страницу, а не заходит в каждого продавца отдельно.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ общей ленты")
    first_id, _ = insert_seller(committing_session, name="Пасека первая")
    second_id, _ = insert_seller(committing_session, name="Пасека вторая")
    client.put(f"/api/v1/admin/sellers/{first_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{second_id}/profile", json={"row": "Ряд 2"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", headers=headers)

    app.dependency_overrides.clear()
    changes = {c["seller_id"]: c for c in response.json()["changes"]}
    assert changes[first_id]["new_value"] == "Ряд 1"
    assert changes[second_id]["new_value"] == "Ряд 2"


def test_feed_distinguishes_seller_and_admin_authors(committing_session):
    # Весь смысл журнала в том, чтобы админ отличал «продавец сам поправил» от
    # «поправил админ»: без этой пары роль-константа в эндпоинте не ловится.
    override_session(committing_session)
    client = TestClient(app)
    headers, admin_user_id = admin_headers(committing_session, client, name="Админ двух ролей")
    seller_id, seller_user_id = insert_seller(committing_session, name="Пасека двух ролей")
    SellerProfileService(committing_session).apply(
        seller_id,
        {"place": "Место продавца"},
        author_user_id=seller_user_id,
        author_role="SELLER",
    )
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд админа"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", headers=headers)

    app.dependency_overrides.clear()
    changes = {c["field"]: c for c in response.json()["changes"] if c["seller_id"] == seller_id}
    assert changes["place"]["author_role"] == "SELLER"
    assert changes["place"]["author_user_id"] == seller_user_id
    assert changes["row"]["author_role"] == "ADMIN"
    assert changes["row"]["author_user_id"] == admin_user_id


def test_feed_seller_name_comes_from_platform_users(committing_session):
    # SellerProduct.seller_name — это наименование товара, как его дал продавец,
    # а не имя продавца (та же ловушка, что в очереди модерации).
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ имени")
    seller_id, _ = insert_seller(committing_session, name="Пасека Ромашково")
    committing_session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, seller_name, unit) "
            "VALUES (:seller_id, 'Мёд гречишный', 'кг')"
        ),
        {"seller_id": seller_id},
    )
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"}, headers=headers)

    response = client.get("/api/v1/admin/profile-changes", headers=headers)

    app.dependency_overrides.clear()
    change = next(c for c in response.json()["changes"] if c["seller_id"] == seller_id)
    assert change["seller_name"] == "Пасека Ромашково"


def test_update_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    seller_id, _ = insert_seller(committing_session, name="Пасека без токена")

    response = client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"})

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"
    assert SellerProfileService(committing_session).read(seller_id)["row"] is None


def test_feed_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/admin/profile-changes")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_admin_update_request_accepts_exactly_the_profile_fields():
    # Зеркало теста продавцовской модели. Седьмое поле, добавленное в fields.py
    # и не добавленное сюда, сервисом принималось бы, а extra="forbid" отвечал
    # бы админу 422 — то самое расхождение между двумя потребителями одного
    # сервиса, ради предотвращения которого forbid и ставился.
    assert set(AdminSellerProfileUpdateRequest.model_fields) == {field.name for field in PROFILE_FIELDS}


def test_admin_profile_response_carries_exactly_the_profile_fields():
    # suggested_phone здесь отсутствует намеренно: это подсказка форме продавца
    # при первом заполнении, админу она не нужна.
    assert set(AdminSellerProfileResponse.model_fields) == {"seller_id", "name", "status"} | {
        field.name for field in PROFILE_FIELDS
    }


def test_admin_reads_seller_profile(committing_session):
    # Без чтения админская правка бессмысленна: форму редактирования нечем
    # заполнить — продавцовский GET требует access_token, которого у админа нет.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ чтения")
    seller_id, _ = insert_seller(committing_session, name="Пасека Ромашково")
    client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile",
        json={"row": "Ряд 3", "phone": "79991112233"},
        headers=headers,
    )

    response = client.get(f"/api/v1/admin/sellers/{seller_id}/profile", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"seller_id", "name", "status"} | {field.name for field in PROFILE_FIELDS}
    assert body["seller_id"] == seller_id
    assert body["name"] == "Пасека Ромашково"
    assert body["status"] == "ACTIVE"
    assert body["row"] == "Ряд 3"
    assert body["phone"] == "79991112233"
    assert body["place"] is None
    assert "suggested_phone" not in body


def test_admin_reads_profile_of_deactivated_seller(committing_session):
    # Покупательская карточка на деактивированного продавца отдаёт 404, но
    # админу нужен именно он: чаще всего правят как раз такого. Отсюда и status
    # в ответе — чтобы деактивация была видна, а не угадывалась.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ деактивированного")
    seller_id, _ = insert_seller(committing_session, name="Пасека деактивированная")
    committing_session.execute(
        text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id}
    )

    response = client.get(f"/api/v1/admin/sellers/{seller_id}/profile", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"
    assert response.json()["seller_id"] == seller_id


def test_admin_profile_read_rejects_unknown_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ чтения несуществующего")

    response = client.get("/api/v1/admin/sellers/999999/profile", headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_admin_profile_read_requires_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    seller_id, _ = insert_seller(committing_session, name="Пасека чтения без токена")

    response = client.get(f"/api/v1/admin/sellers/{seller_id}/profile")

    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_admin_update_clears_field_with_empty_string(committing_session):
    # Та же семантика, что у продавца: отсутствие ключа — «не трогать», пустая
    # строка — «очистить». Через HTTP она была доказана только на одной стороне.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ очистки")
    seller_id, _ = insert_seller(committing_session, name="Пасека очистки")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"}, headers=headers)

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": ""}, headers=headers
    )
    saved = client.get(f"/api/v1/admin/sellers/{seller_id}/profile", headers=headers).json()

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["changed"] == ["row"]
    assert saved["row"] is None


def test_admin_update_without_changes_returns_empty_changed(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ без изменений")
    seller_id, _ = insert_seller(committing_session, name="Пасека без изменений")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"}, headers=headers)

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 3"}, headers=headers
    )

    # Повторная отправка формы без правок не должна попадать в ленту админа:
    # иначе лента забьётся строками «изменил row на то же самое».
    feed = client.get("/api/v1/admin/profile-changes", headers=headers).json()

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["changed"] == []
    assert len([c for c in feed["changes"] if c["seller_id"] == seller_id]) == 1


def test_admin_update_returns_changed_in_profile_field_order(committing_session):
    # Порядок changed следует PROFILE_FIELDS, а не порядку ключей в запросе:
    # ответ не должен зависеть от того, как клиент собрал JSON. Все остальные
    # тесты оборачивают changed в sorted() и эту гарантию не проверяют.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ порядка полей")
    seller_id, _ = insert_seller(committing_session, name="Пасека порядка полей")

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile",
        json={"whatsapp": "79990000001", "row": "Ряд 3", "place": "Место 12"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.json()["changed"] == ["row", "place", "whatsapp"]


def latest_change_id(client, headers) -> int:
    """Максимальный id ленты на текущий момент. Лента глобальная, и привязка к
    абсолютным значениям сделала бы тесты зависимыми от содержимого базы."""
    body = client.get("/api/v1/admin/profile-changes", params={"limit": 1}, headers=headers).json()
    return body["changes"][0]["id"] if body["changes"] else 0


def test_feed_reports_total_beyond_the_page(committing_session):
    # Без total Cabinet не отличит полную страницу от обрезанной и не поймёт,
    # есть ли что-то за пределами выдачи.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ total")
    seller_id, _ = insert_seller(committing_session, name="Пасека total")
    baseline = latest_change_id(client, headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"place": "Место 2"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"phone": "79990000000"}, headers=headers)

    response = client.get(
        "/api/v1/admin/profile-changes", params={"limit": 2, "after_id": baseline}, headers=headers
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert len(body["changes"]) == 2
    assert body["total"] == 3


def test_feed_after_id_returns_only_newer_changes(committing_session):
    # «Что нового с прошлого раза»: клиент запоминает максимальный id выдачи —
    # иначе замену уведомлений приходится строить на дедупликации всей ленты.
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ after_id")
    seller_id, _ = insert_seller(committing_session, name="Пасека after_id")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    seen = latest_change_id(client, headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"place": "Место 2"}, headers=headers)

    response = client.get(
        "/api/v1/admin/profile-changes", params={"after_id": seen}, headers=headers
    )

    app.dependency_overrides.clear()
    body = response.json()
    assert [c["field"] for c in body["changes"]] == ["place"]
    assert body["total"] == 1
    assert all(c["id"] > seen for c in body["changes"])


def test_feed_after_id_at_latest_change_returns_nothing(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ пустой ленты")
    seller_id, _ = insert_seller(committing_session, name="Пасека пустой ленты")
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)

    response = client.get(
        "/api/v1/admin/profile-changes",
        params={"after_id": latest_change_id(client, headers)},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"changes": [], "total": 0}

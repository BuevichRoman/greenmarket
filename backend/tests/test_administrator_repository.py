from sqlalchemy import text

from app.infrastructure.repositories.administrator_repository import AdministratorRepository


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def test_create_persists_active_administrator_without_credentials(session):
    user_id = insert_user(session, name="Пользователь для создания админа")
    repository = AdministratorRepository(session)

    created = repository.create(user_id=user_id)

    assert created.id is not None
    assert created.is_active is True
    assert created.access_token is None
    assert created.activation_code is None


def test_find_by_user_id_returns_created_administrator(session):
    user_id = insert_user(session, name="Пользователь для поиска админа")
    repository = AdministratorRepository(session)
    created = repository.create(user_id=user_id)

    found = repository.find_by_user_id(user_id)

    assert found is not None
    assert found.id == created.id


def test_find_by_user_id_returns_none_for_user_without_administrator(session):
    user_id = insert_user(session, name="Пользователь без админки")

    assert AdministratorRepository(session).find_by_user_id(user_id) is None


def test_find_by_access_token_ignores_empty_token(session):
    """Пустая строка не должна находить админа с NULL-токеном — иначе
    неактивированная учётка открывала бы доступ без токена вообще."""
    user_id = insert_user(session, name="Неактивированный админ")
    AdministratorRepository(session).create(user_id=user_id)

    assert AdministratorRepository(session).find_by_access_token("") is None

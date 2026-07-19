import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.database import SessionLocal, engine, test_engine


@pytest.fixture
def session():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture
def seller_product_id(session) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для фото"}).lastrowid
    seller_id = session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid
    return session.execute(
        text("INSERT INTO SellerProduct (seller_id, seller_name, unit) VALUES (:seller_id, :seller_name, :unit)"),
        {"seller_id": seller_id, "seller_name": "Товар для фото", "unit": "шт"},
    ).lastrowid


@pytest.fixture
def committing_session():
    """Сессия для тестов Publication Service — единственного компонента,
    которому по контракту разрешено реально коммитить (`session.commit()`).
    Обычная фикстура `session` полагается на то, что тест никогда не коммитит
    (откат происходит просто закрытием без commit), но здесь commit — часть
    проверяемого поведения, поэтому используется вложенная транзакция
    (SAVEPOINT): `session.commit()`/`rollback()` внутри теста работают на
    уровне SAVEPOINT, а внешняя транзакция соединения откатывается в конце
    теста целиком — БД не засоряется тестовыми публикациями.
    """
    connection = engine.connect()
    transaction = connection.begin()
    db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db_session
    finally:
        db_session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def test_committing_session():
    """Та же механика, что committing_session, но на ОТДЕЛЬНОЙ схеме
    (greenmarket_test, TEST_DB_NAME) — нужна, чтобы тесты могли реально
    проверить, что Mode=TEST пишет в другую БД, а не просто доверять коду."""
    if test_engine is None:
        pytest.skip("TEST_DB_NAME не настроен — тестовая схема недоступна")
    connection = test_engine.connect()
    transaction = connection.begin()
    db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db_session
    finally:
        db_session.close()
        transaction.rollback()
        connection.close()

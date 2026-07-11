import pytest
from sqlalchemy.orm import Session

from app.infrastructure.database import SessionLocal, engine


@pytest.fixture
def session():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


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

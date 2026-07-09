import pytest

from app.infrastructure.database import SessionLocal


@pytest.fixture
def session():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

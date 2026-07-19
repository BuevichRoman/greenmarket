from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

DATABASE_URL = (
    f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Схема для Mode=TEST в рабочей книге продавца (см. app/publication/mode.py) —
# та же БД-инстанс, отдельная схема, не aristotel_taxi. Не настроена → None,
# запрос с Mode=TEST на таком окружении получит понятную ошибку, а не тихий
# фоллбэк на боевую БД.
test_engine = None
TestSessionLocal = None
if settings.test_db_name:
    TEST_DATABASE_URL = (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.test_db_name}"
    )
    test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_test_session() -> Session | None:
    if TestSessionLocal is None:
        yield None
        return
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()

"""Сессия сверки каталога и её построчный снимок.

Baseline существует ради одного инварианта: в момент создания состояние базы и
книги совпадают, а дальше расходятся — и это расхождение потом и ищется.
Поэтому снимок неизменен, а создать его нельзя, не доказав равенство.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.application.catalog_sync_use_case import CatalogSyncUseCase
from app.infrastructure.models import CatalogSyncSession
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.sync.errors import (
    BaselineInProgressError,
    SheetCatalogMismatchError,
    SyncSessionExpiredError,
    SyncSessionNotFoundError,
    SyncSessionNotInvalidatableError,
)
from app.sync.fingerprint import catalog_fingerprint


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:n)"), {"n": name}).lastrowid


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:u)"), {"u": user_id}).lastrowid


def add_offer(session, seller_id, *, name, price=100, origin=None):
    return SellerProductRepository(session).create(
        seller_id=seller_id, product_id=None, seller_name=name, price=price, stock=1,
        unit="кг", description=None, is_published=False, origin_country=origin,
    )


def sync(session) -> CatalogSyncUseCase:
    return CatalogSyncUseCase(session)


def current_hash(session, seller_id: int) -> str:
    return catalog_fingerprint(SellerProductRepository(session).list_by_seller(seller_id))


def expire(session, session_id: str) -> None:
    """Отодвигаем срок в прошлое через ORM, а не сырым UPDATE: загруженный
    объект иначе остаётся с прежним значением и тест проверял бы кэш."""
    row = (
        session.query(CatalogSyncSession)
        .filter(CatalogSyncSession.session_id == session_id)
        .one()
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.flush()


# ── Сессия ───────────────────────────────────────────────────────────────────


def test_create_session_is_active_without_baseline(session):
    seller_id = insert_seller(session, name="Ферма сессии")

    created = sync(session).create_session(seller_id)

    state = sync(session).load_session(seller_id, created.session_id)
    assert state.status == "ACTIVE"
    assert state.baseline_ready is False
    assert state.row.expires_at > state.row.created_at


def test_repeated_create_session_with_same_key_returns_the_same_session(session):
    seller_id = insert_seller(session, name="Ферма повтора сессии")
    key = str(uuid.uuid4())

    first = sync(session).create_session(seller_id, idempotency_key=key)
    second = sync(session).create_session(seller_id, idempotency_key=key)

    assert first.session_id == second.session_id


def test_session_of_another_seller_looks_like_missing(session):
    mine = insert_seller(session, name="Ферма своя сессия")
    theirs = insert_seller(session, name="Ферма чужая сессия")
    foreign = sync(session).create_session(theirs)

    with pytest.raises(SyncSessionNotFoundError):
        sync(session).load_session(mine, foreign.session_id)


def test_expired_session_reports_expired_on_read(session):
    seller_id = insert_seller(session, name="Ферма истечения")
    created = sync(session).create_session(seller_id)
    expire(session, created.session_id)

    assert sync(session).load_session(seller_id, created.session_id).status == "EXPIRED"


def test_invalidate_marks_session_invalidated(session):
    seller_id = insert_seller(session, name="Ферма инвалидации")
    created = sync(session).create_session(seller_id)

    sync(session).invalidate(seller_id, created.session_id)

    assert sync(session).load_session(seller_id, created.session_id).status == "INVALIDATED"


# ── Снимок ───────────────────────────────────────────────────────────────────


def test_baseline_snapshots_every_position(session):
    seller_id = insert_seller(session, name="Ферма снимка")
    first = add_offer(session, seller_id, name="Первый товар снимка")
    second = add_offer(session, seller_id, name="Второй товар снимка")
    created = sync(session).create_session(seller_id)

    rows = sync(session).create_baseline(
        seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id)
    )

    assert {r.seller_product_id for r in rows} == {first.id, second.id}
    assert sync(session).load_session(seller_id, created.session_id).baseline_ready is True


def test_baseline_is_refused_when_sheet_hash_differs(session):
    """Шлюз: без доказанного равенства базы и книги снимок не создаётся."""
    seller_id = insert_seller(session, name="Ферма расхождения")
    add_offer(session, seller_id, name="Товар расхождения")
    created = sync(session).create_session(seller_id)

    with pytest.raises(SheetCatalogMismatchError):
        sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash="не тот отпечаток")

    assert sync(session).load_session(seller_id, created.session_id).baseline_ready is False


def test_repeated_baseline_request_returns_the_first_one(session):
    seller_id = insert_seller(session, name="Ферма повтора снимка")
    add_offer(session, seller_id, name="Товар повтора снимка")
    created = sync(session).create_session(seller_id)
    digest = current_hash(session, seller_id)

    first = sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=digest)
    second = sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=digest)

    assert len(first) == len(second) == 1
    total = session.execute(
        text("SELECT COUNT(*) FROM CatalogSyncBaseline b JOIN CatalogSyncSession s ON s.id = b.session_id "
             "WHERE s.session_id = :s"), {"s": created.session_id},
    ).scalar()
    assert total == 1


def test_baseline_does_not_follow_the_catalog(session):
    """Снимок неизменен: правка каталога после его создания на него не влияет."""
    seller_id = insert_seller(session, name="Ферма неизменности")
    offer = add_offer(session, seller_id, name="Товар неизменности", price=100)
    created = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id))

    offer.price = 120
    offer.version += 1
    session.flush()

    rows = sync(session).get_baseline(seller_id, created.session_id)
    assert float(rows[0].price) == 100


def test_baseline_cannot_be_created_for_expired_session(session):
    seller_id = insert_seller(session, name="Ферма снимка истёкшей")
    add_offer(session, seller_id, name="Товар истёкшей сессии")
    created = sync(session).create_session(seller_id)
    expire(session, created.session_id)

    with pytest.raises(SyncSessionExpiredError):
        sync(session).create_baseline(
            seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id)
        )


def test_parallel_sessions_keep_independent_baselines(session):
    seller_id = insert_seller(session, name="Ферма двух вкладок")
    offer = add_offer(session, seller_id, name="Товар двух вкладок", price=100)
    first = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, first.session_id, sheet_catalog_hash=current_hash(session, seller_id))

    offer.price = 200
    offer.version += 1
    session.flush()
    second = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, second.session_id, sheet_catalog_hash=current_hash(session, seller_id))

    assert float(sync(session).get_baseline(seller_id, first.session_id)[0].price) == 100
    assert float(sync(session).get_baseline(seller_id, second.session_id)[0].price) == 200


def test_session_reports_db_change_after_baseline(session):
    """Публикация из книги тоже поднимает version — сессия обязана это увидеть."""
    seller_id = insert_seller(session, name="Ферма расхождения версий")
    offer = add_offer(session, seller_id, name="Товар расхождения версий")
    created = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id))

    assert sync(session).load_session(seller_id, created.session_id).db_changed_since_baseline is False

    offer.version += 1
    session.flush()

    assert sync(session).load_session(seller_id, created.session_id).db_changed_since_baseline is True


def test_baseline_of_another_seller_is_not_readable(session):
    mine = insert_seller(session, name="Ферма своего снимка")
    theirs = insert_seller(session, name="Ферма чужого снимка")
    add_offer(session, theirs, name="Чужой товар снимка")
    foreign = sync(session).create_session(theirs)
    sync(session).create_baseline(theirs, foreign.session_id, sheet_catalog_hash=current_hash(session, theirs))

    with pytest.raises(SyncSessionNotFoundError):
        sync(session).get_baseline(mine, foreign.session_id)


# ── Отпечаток ────────────────────────────────────────────────────────────────


def test_fingerprint_notices_origin_country(session):
    """Страна происхождения есть в книге и правится продавцом, значит обязана
    входить в отпечаток: иначе шлюз пропустит неравные состояния."""
    seller_id = insert_seller(session, name="Ферма страны происхождения")
    offer = add_offer(session, seller_id, name="Товар страны", origin="Армения")
    before = current_hash(session, seller_id)

    offer.origin_country = "Грузия"
    session.flush()

    assert current_hash(session, seller_id) != before


def test_fingerprint_does_not_depend_on_row_order(session):
    seller_id = insert_seller(session, name="Ферма порядка строк")
    add_offer(session, seller_id, name="Первый порядок")
    add_offer(session, seller_id, name="Второй порядок")
    rows = SellerProductRepository(session).list_by_seller(seller_id)

    assert catalog_fingerprint(rows) == catalog_fingerprint(list(reversed(rows)))


# ── Замечания ревью: гонки и инвариант версии ────────────────────────────────


def test_concurrent_session_creation_with_same_key_returns_the_winner(session):
    """Гонка: второй запрос не увидел первую сессию при чтении и упёрся в
    уникальный ключ. Это тот же повтор, а не ошибка клиента."""
    seller_id = insert_seller(session, name="Ферма гонки ключа")
    key = str(uuid.uuid4())
    use_case = sync(session)
    first = use_case.create_session(seller_id, idempotency_key=key)

    # Имитируем проигравшего: при чтении он сессии не видит и идёт вставлять.
    use_case._find_by_idempotency_key = _MissOnce(use_case._find_by_idempotency_key)

    second = use_case.create_session(seller_id, idempotency_key=key)

    assert second.session_id == first.session_id


class _MissOnce:
    """Первый вызов «не находит» — так воспроизводится окно между чтением и
    вставкой, в котором чужая транзакция успевает закоммитить сессию."""

    def __init__(self, original):
        self._original = original
        self._missed = False

    def __call__(self, *args, **kwargs):
        if not self._missed:
            self._missed = True
            return None
        return self._original(*args, **kwargs)


def test_concurrent_baseline_creation_does_not_return_empty_snapshot(session):
    """Отметка стоит, строк ещё нет: их дописывает другая транзакция. Отдать
    пустой снимок значило бы выдать пустой каталог за состояние."""
    seller_id = insert_seller(session, name="Ферма гонки снимка")
    add_offer(session, seller_id, name="Товар гонки снимка")
    created = sync(session).create_session(seller_id)
    row = (
        session.query(CatalogSyncSession)
        .filter(CatalogSyncSession.session_id == created.session_id)
        .one()
    )
    row.baseline_created_at = datetime.now(timezone.utc)
    session.flush()

    with pytest.raises(BaselineInProgressError):
        sync(session).create_baseline(
            seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id)
        )


def test_completed_session_cannot_be_invalidated(session):
    seller_id = insert_seller(session, name="Ферма завершённой сессии")
    created = sync(session).create_session(seller_id)
    sync(session).complete(seller_id, created.session_id)

    with pytest.raises(SyncSessionNotInvalidatableError):
        sync(session).invalidate(seller_id, created.session_id)


def test_invalidating_expired_session_is_a_no_op(session):
    seller_id = insert_seller(session, name="Ферма отмены истёкшей")
    created = sync(session).create_session(seller_id)
    expire(session, created.session_id)

    sync(session).invalidate(seller_id, created.session_id)

    assert sync(session).load_session(seller_id, created.session_id).status == "EXPIRED"


def test_added_position_shows_up_as_db_change(session):
    """Появление позиции после снимка — тоже изменение: для трёхстороннего
    сравнения добавление так же значимо, как правка."""
    seller_id = insert_seller(session, name="Ферма добавления после снимка")
    add_offer(session, seller_id, name="Исходный товар")
    created = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id))

    add_offer(session, seller_id, name="Товар, добавленный после снимка")
    session.flush()

    assert sync(session).load_session(seller_id, created.session_id).db_changed_since_baseline is True


def test_deactivation_bumps_version_and_shows_up_as_db_change(session):
    """Снятие с витрины обязано менять version — иначе сессия не заметила бы
    исчезновения товара у покупателя."""
    seller_id = insert_seller(session, name="Ферма снятия после снимка")
    offer = add_offer(session, seller_id, name="Товар снятия")
    offer.is_published = True
    session.flush()
    created = sync(session).create_session(seller_id)
    sync(session).create_baseline(seller_id, created.session_id, sheet_catalog_hash=current_hash(session, seller_id))
    before = offer.version

    offer.is_published = False
    offer.version += 1
    session.flush()

    assert offer.version == before + 1
    assert sync(session).load_session(seller_id, created.session_id).db_changed_since_baseline is True

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.models import CatalogSyncBaseline, CatalogSyncSession
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.sync.errors import (
    BaselineNotReadyError,
    SheetCatalogMismatchError,
    SyncSessionExpiredError,
    SyncSessionNotFoundError,
)
from app.sync.fingerprint import catalog_fingerprint

SESSION_TTL = timedelta(hours=24)
SESSION_RETENTION = timedelta(days=90)

ACTIVE = "ACTIVE"
EXPIRED = "EXPIRED"
COMPLETED = "COMPLETED"
INVALIDATED = "INVALIDATED"

_CLOSED = (EXPIRED, COMPLETED, INVALIDATED)


@dataclass(frozen=True)
class SessionState:
    """То, что видит клиент: сессия плюс два вычисляемых признака."""

    row: CatalogSyncSession
    status: str
    baseline_ready: bool
    db_changed_since_baseline: bool


class CatalogSyncUseCase:
    """Рабочая сессия сверки каталога с книгой и её построчный снимок.

    Снимок неизменен: он фиксирует момент, когда база и книга совпадали, и
    дальше служит точкой отсчёта. Поэтому создать его нельзя, не доказав
    равенство, а обновить нельзя вовсе — новое исходное состояние означает
    новую сессию.
    """

    def __init__(self, session: Session):
        self.session = session
        self.seller_product_repository = SellerProductRepository(session)

    # ── Сессия ───────────────────────────────────────────────────────────────

    def create_session(self, seller_id: int, *, idempotency_key: str | None = None) -> CatalogSyncSession:
        if idempotency_key is not None:
            existing = (
                self.session.query(CatalogSyncSession)
                .filter(
                    CatalogSyncSession.seller_id == seller_id,
                    CatalogSyncSession.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is not None:
                return existing

        now = datetime.now(timezone.utc)
        row = CatalogSyncSession(
            session_id=str(uuid.uuid4()),
            seller_id=seller_id,
            status=ACTIVE,
            created_at=now,
            expires_at=now + SESSION_TTL,
            baseline_created_at=None,
            idempotency_key=idempotency_key,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def load_session(self, seller_id: int, session_id: str) -> SessionState:
        row = self._own_session(seller_id, session_id)
        self._collect_finished_baselines(seller_id)
        status = self._effective_status(row)
        baseline_ready = row.baseline_created_at is not None
        return SessionState(
            row=row,
            status=status,
            baseline_ready=baseline_ready,
            db_changed_since_baseline=baseline_ready and self._db_changed(row),
        )

    def invalidate(self, seller_id: int, session_id: str) -> CatalogSyncSession:
        row = self._own_session(seller_id, session_id)
        row.status = INVALIDATED
        self.session.flush()
        return row

    def complete(self, seller_id: int, session_id: str) -> CatalogSyncSession:
        """Ставится по факту успешной публикации книги, а не запросом клиента:
        иначе «сверка завершена» можно было бы получить без публикации."""
        row = self._own_session(seller_id, session_id)
        self._require_usable(row)
        row.status = COMPLETED
        self.session.flush()
        return row

    # ── Снимок ───────────────────────────────────────────────────────────────

    def create_baseline(
        self, seller_id: int, session_id: str, *, sheet_catalog_hash: str
    ) -> list[CatalogSyncBaseline]:
        row = self._own_session(seller_id, session_id)
        self._require_usable(row)

        if row.baseline_created_at is not None:
            return self._baseline_rows(row.id)

        # Всё дальнейшее — одна транзакция: снимок и отметка о нём фиксируются
        # вместе, поэтому частично записанный baseline увидеть нельзя. Прод в
        # REPEATABLE READ, так что чтение каталога внутри неё согласовано.
        products = self.seller_product_repository.list_by_seller(seller_id)
        if catalog_fingerprint(products) != sheet_catalog_hash:
            raise SheetCatalogMismatchError(
                "Состояние книги не совпадает с каталогом: сверка не выполнена"
            )

        # Замок — сама строка сессии: условный UPDATE из NULL. Ноль затронутых
        # строк означает, что снимок уже создаёт кто-то другой, и второго
        # baseline не появится.
        claimed = self.session.execute(
            text(
                "UPDATE CatalogSyncSession SET baseline_created_at = :now "
                "WHERE id = :id AND baseline_created_at IS NULL"
            ),
            {"now": datetime.now(timezone.utc), "id": row.id},
        ).rowcount
        if not claimed:
            self.session.refresh(row)
            return self._baseline_rows(row.id)

        for product in products:
            self.session.add(
                CatalogSyncBaseline(
                    session_id=row.id,
                    seller_product_id=product.id,
                    seller_sku=product.seller_sku,
                    product_id=product.product_id,
                    seller_name=product.seller_name,
                    price=product.price,
                    stock=product.stock,
                    unit=product.unit,
                    description=product.description,
                    origin_country=product.origin_country,
                    supply_date=product.supply_date,
                    is_published=bool(product.is_published),
                    version=product.version,
                )
            )
        self.session.flush()
        self.session.refresh(row)
        return self._baseline_rows(row.id)

    def get_baseline(self, seller_id: int, session_id: str) -> list[CatalogSyncBaseline]:
        row = self._own_session(seller_id, session_id)
        if row.baseline_created_at is None:
            raise BaselineNotReadyError(f"У сессии {session_id} ещё нет снимка")
        return self._baseline_rows(row.id)

    # ── Внутреннее ───────────────────────────────────────────────────────────

    def _own_session(self, seller_id: int, session_id: str) -> CatalogSyncSession:
        row = (
            self.session.query(CatalogSyncSession)
            .filter(
                CatalogSyncSession.session_id == session_id,
                CatalogSyncSession.seller_id == seller_id,
            )
            .first()
        )
        if row is None:
            raise SyncSessionNotFoundError(f"Сессия сверки {session_id} не найдена")
        return row

    def _effective_status(self, row: CatalogSyncSession) -> str:
        """Истечение считается по времени, а не по записанному статусу:
        планировщика в системе нет, и «протухание» не должно зависеть от того,
        работал ли воркер."""
        if row.status == ACTIVE and self._is_past(row.expires_at):
            return EXPIRED
        return row.status

    def _require_usable(self, row: CatalogSyncSession) -> None:
        status = self._effective_status(row)
        if status != ACTIVE:
            raise SyncSessionExpiredError(f"Сессия сверки {row.session_id} в состоянии {status}")

    def _db_changed(self, row: CatalogSyncSession) -> bool:
        """Разошлись ли версии позиций с момента снимка.

        Само по себе расхождение ошибкой не является: после создания снимка база
        и книга и должны расходиться — это и есть предмет сверки. Признак нужен
        клиенту, чтобы решить, пересчитывать ли diff.
        """
        baseline = {b.seller_product_id: b.version for b in self._baseline_rows(row.id)}
        current = {p.id: p.version for p in self.seller_product_repository.list_by_seller(row.seller_id)}
        return baseline != current

    def _baseline_rows(self, session_row_id: int) -> list[CatalogSyncBaseline]:
        return (
            self.session.query(CatalogSyncBaseline)
            .filter(CatalogSyncBaseline.session_id == session_row_id)
            .order_by(CatalogSyncBaseline.seller_product_id)
            .all()
        )

    def _collect_finished_baselines(self, seller_id: int) -> None:
        """Ленивая очистка вместо воркера: снимок завершённой или истёкшей
        сессии своё отработал, а строк в нём столько же, сколько позиций в
        каталоге. Сама сессия остаётся следом и удаляется по сроку хранения."""
        now = datetime.now(timezone.utc)
        finished = (
            self.session.query(CatalogSyncSession.id)
            .filter(
                CatalogSyncSession.seller_id == seller_id,
                CatalogSyncSession.baseline_created_at.isnot(None),
                (CatalogSyncSession.status.in_(_CLOSED)) | (CatalogSyncSession.expires_at < now),
            )
            .all()
        )
        ids = [row[0] for row in finished]
        if ids:
            self.session.query(CatalogSyncBaseline).filter(
                CatalogSyncBaseline.session_id.in_(ids)
            ).delete(synchronize_session=False)

    @staticmethod
    def _is_past(moment: datetime) -> bool:
        # Из MySQL DATETIME приходит без зоны — сравниваем в UTC явно.
        reference = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
        return reference < datetime.now(timezone.utc)

from datetime import datetime
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SellerStatus:
    is_active: bool
    current_catalog_version: int


@dataclass(frozen=True)
class ActivationLookup:
    seller_id: int
    activation_code_expires_at: datetime | None


@dataclass(frozen=True)
class SellerAccessRow:
    seller_id: int
    user_id: int
    name: str


@dataclass(frozen=True)
class SellerListRow:
    """Основная информация о продавце для Admin Cabinet (Admin_MVP.md, экран 4).

    `activated_at` и `activation_code_expires_at` вместе отвечают на вопрос, на
    каком шаге подключения продавец: код выдан, но не обменян — ждём продавца;
    `activated_at` заполнен — работает.
    """

    seller_id: int
    user_id: int
    name: str
    is_active: bool
    current_catalog_version: int
    activated_at: datetime | None
    activation_code_expires_at: datetime | None


class SellerGateway:
    """Читает минимально необходимые платформенные данные Seller напрямую из БД.

    GreenMarket не владеет Seller и не мапит его как ORM-модель (см.
    app/infrastructure/models.py) — это Anti-Corruption Layer, согласовано с
    коллегой (kwork/timeline.md, п.38): если источник данных платформы
    сменится (REST/gRPC API платформы вместо прямого доступа к БД), меняется
    только этот файл, а не Validator.
    """

    def __init__(self, session: Session):
        self.session = session

    def get_status(self, seller_id: int) -> SellerStatus | None:
        row = self.session.execute(
            text("SELECT is_active, current_catalog_version FROM Seller WHERE id = :seller_id"),
            {"seller_id": seller_id},
        ).first()
        if row is None:
            return None
        return SellerStatus(is_active=bool(row[0]), current_catalog_version=row[1] or 0)

    def get_current_publication_key(self, seller_id: int) -> str | None:
        row = self.session.execute(
            text("SELECT current_publication_key FROM Seller WHERE id = :seller_id"),
            {"seller_id": seller_id},
        ).first()
        return row[0] if row else None

    def get_current_catalog_hash(self, seller_id: int) -> str | None:
        row = self.session.execute(
            text("SELECT current_catalog_hash FROM Seller WHERE id = :seller_id"),
            {"seller_id": seller_id},
        ).first()
        return row[0] if row else None

    def update_current_publication(self, seller_id: int, *, publication_key: str, catalog_hash: str, catalog_version: int) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET current_publication_key = :publication_key, "
                "current_catalog_hash = :catalog_hash, current_catalog_version = :catalog_version "
                "WHERE id = :seller_id"
            ),
            {
                "seller_id": seller_id,
                "publication_key": publication_key,
                "catalog_hash": catalog_hash,
                "catalog_version": catalog_version,
            },
        )

    def list_active_seller_ids(self, seller_ids: list[int]) -> set[int]:
        if not seller_ids:
            return set()
        stmt = text("SELECT id FROM Seller WHERE id IN :seller_ids AND is_active = TRUE").bindparams(
            bindparam("seller_ids", expanding=True)
        )
        rows = self.session.execute(stmt, {"seller_ids": seller_ids}).all()
        return {row[0] for row in rows}

    def list_seller_names(self, seller_ids: list[int]) -> dict[int, str]:
        """Отображаемые имена продавцов из платформенной users (см. Seller_Profile.md,
        поле `name`) — SellerProduct.seller_name хранит название товара продавца,
        а не продавца."""
        if not seller_ids:
            return {}
        stmt = text(
            "SELECT s.id, u.name FROM Seller s JOIN users u ON u.id_user = s.user_id WHERE s.id IN :seller_ids"
        ).bindparams(bindparam("seller_ids", expanding=True))
        rows = self.session.execute(stmt, {"seller_ids": seller_ids}).all()
        return {row[0]: row[1] for row in rows}

    def user_exists(self, user_id: int) -> bool:
        """Существует ли пользователь платформы. FK не даст создать Seller на
        несуществующего, но проверка нужна раньше — чтобы админ получил
        человеческий ответ, а не ошибку целостности из драйвера."""
        return (
            self.session.execute(
                text("SELECT 1 FROM users WHERE id_user = :user_id"), {"user_id": user_id}
            ).first()
            is not None
        )

    def find_seller_id_by_user(self, user_id: int) -> int | None:
        row = self.session.execute(
            text("SELECT id FROM Seller WHERE user_id = :user_id"), {"user_id": user_id}
        ).first()
        return None if row is None else row[0]

    def create(self, user_id: int) -> int:
        """Заводит учётную запись продавца. Раньше строку Seller можно было
        создать только руками через SQL — единственные INSERT'ы жили в
        демо-сидерах, то есть боевой онбординг требовал доступа к серверу."""
        return self.session.execute(
            text("INSERT INTO Seller (user_id, is_active, created_at, updated_at) VALUES (:user_id, TRUE, NOW(), NOW())"),
            {"user_id": user_id},
        ).lastrowid

    _LIST_COLUMNS = (
        "SELECT s.id, s.user_id, u.name, s.is_active, s.current_catalog_version, "
        "s.activated_at, s.activation_code_expires_at "
        "FROM Seller s JOIN users u ON u.id_user = s.user_id "
    )

    @staticmethod
    def _to_list_row(row) -> SellerListRow:
        return SellerListRow(
            seller_id=row[0],
            user_id=row[1],
            name=row[2],
            is_active=bool(row[3]),
            current_catalog_version=row[4] or 0,
            activated_at=row[5],
            activation_code_expires_at=row[6],
        )

    def list_all(self) -> list[SellerListRow]:
        rows = self.session.execute(text(self._LIST_COLUMNS + "ORDER BY s.id")).all()
        return [self._to_list_row(row) for row in rows]

    def find_list_row(self, seller_id: int) -> SellerListRow | None:
        row = self.session.execute(
            text(self._LIST_COLUMNS + "WHERE s.id = :seller_id"), {"seller_id": seller_id}
        ).first()
        return None if row is None else self._to_list_row(row)

    def set_active(self, seller_id: int, *, is_active: bool) -> None:
        """Временная деактивация и возврат в активное состояние. Каталог, его
        публикации и SellerProduct не трогаются — скрывается только видимость
        покупателю (Admin_MVP.md, «Временная деактивация»)."""
        self.session.execute(
            text("UPDATE Seller SET is_active = :is_active, updated_at = NOW() WHERE id = :seller_id"),
            {"is_active": is_active, "seller_id": seller_id},
        )

    def clear_activation_code(self, seller_id: int) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET activation_code = NULL, activation_code_expires_at = NULL "
                "WHERE id = :seller_id"
            ),
            {"seller_id": seller_id},
        )

    def find_by_activation_code(self, activation_code: str) -> ActivationLookup | None:
        row = self.session.execute(
            text("SELECT id, activation_code_expires_at FROM Seller WHERE activation_code = :code"),
            {"code": activation_code},
        ).first()
        if row is None:
            return None
        return ActivationLookup(seller_id=row[0], activation_code_expires_at=row[1])

    def set_activation_code(self, seller_id: int, *, activation_code: str, expires_at: datetime) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET activation_code = :code, activation_code_expires_at = :expires_at "
                "WHERE id = :seller_id"
            ),
            {"code": activation_code, "expires_at": expires_at, "seller_id": seller_id},
        )

    def set_access_token(self, seller_id: int, *, access_token: str, spreadsheet_id: str) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET access_token = :access_token, spreadsheet_id = :spreadsheet_id, "
                "activated_at = NOW(), activation_code = NULL, activation_code_expires_at = NULL "
                "WHERE id = :seller_id"
            ),
            {"access_token": access_token, "spreadsheet_id": spreadsheet_id, "seller_id": seller_id},
        )

    def find_by_access_token(self, access_token: str) -> SellerAccessRow | None:
        """`is_active` здесь намеренно не проверяется: временная деактивация
        скрывает каталог от покупателей, но продавца не отключает — кабинет и
        публикация ему остаются (решение коллеги от 2026-08-05, Admin_MVP.md
        «Временная деактивация»). Видимость покупателю фильтруется отдельно —
        list_active_seller_ids."""
        row = self.session.execute(
            text(
                "SELECT s.id, s.user_id, u.name FROM Seller s "
                "JOIN users u ON u.id_user = s.user_id "
                "WHERE s.access_token = :token"
            ),
            {"token": access_token},
        ).first()
        if row is None:
            return None
        return SellerAccessRow(seller_id=row[0], user_id=row[1], name=row[2])

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


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

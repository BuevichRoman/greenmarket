from sqlalchemy import text
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

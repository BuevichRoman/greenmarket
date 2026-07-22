from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class PhotoGateway:
    """Читает и пишет минимально необходимые платформенные данные Photo
    напрямую из БД (raw SQL, не ORM — см. app/infrastructure/models.py,
    комментарий про платформенные таблицы Seller/User/Photo). Anti-Corruption
    Layer, тот же паттерн, что SellerGateway.
    """

    def __init__(self, session: Session):
        self.session = session

    def list_by_seller_products(self, seller_product_ids: list[int]) -> dict[int, list[str]]:
        if not seller_product_ids:
            return {}
        stmt = text(
            "SELECT spp.seller_product_id, p.s3_key "
            "FROM SellerProductPhoto spp "
            "JOIN Photo p ON p.id = spp.photo_id "
            "WHERE spp.seller_product_id IN :seller_product_ids "
            "ORDER BY spp.seller_product_id, spp.sort_order"
        ).bindparams(bindparam("seller_product_ids", expanding=True))
        rows = self.session.execute(stmt, {"seller_product_ids": seller_product_ids}).all()
        result: dict[int, list[str]] = defaultdict(list)
        for seller_product_id, s3_key in rows:
            result[seller_product_id].append(s3_key)
        return dict(result)

    def create(self, *, s3_key: str, seller_id: int) -> int:
        result = self.session.execute(
            text("INSERT INTO Photo (s3_key, seller_id, created_at) VALUES (:s3_key, :seller_id, :created_at)"),
            {"s3_key": s3_key, "seller_id": seller_id, "created_at": datetime.now(timezone.utc)},
        )
        return result.lastrowid

    def exists_all(self, photo_ids: list[int]) -> bool:
        if not photo_ids:
            return True
        stmt = text("SELECT COUNT(*) FROM Photo WHERE id IN :photo_ids").bindparams(
            bindparam("photo_ids", expanding=True)
        )
        count = self.session.execute(stmt, {"photo_ids": photo_ids}).scalar_one()
        return count == len(set(photo_ids))

    def list_by_ids_and_seller(self, photo_ids: list[int], seller_id: int) -> list[tuple[int, str]]:
        if not photo_ids:
            return []
        stmt = text(
            "SELECT id, s3_key FROM Photo WHERE id IN :photo_ids AND seller_id = :seller_id"
        ).bindparams(bindparam("photo_ids", expanding=True))
        rows = self.session.execute(stmt, {"photo_ids": photo_ids, "seller_id": seller_id}).all()
        return [(row[0], row[1]) for row in rows]

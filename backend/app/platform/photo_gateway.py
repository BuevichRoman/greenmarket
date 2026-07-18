from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class PhotoGateway:
    """Читает минимально необходимые платформенные данные Photo напрямую из БД.

    Photo не мапится как ORM-модель (см. app/infrastructure/models.py) — тот же
    Anti-Corruption Layer, что и SellerGateway: если источник фото сменится,
    меняется только этот файл.
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

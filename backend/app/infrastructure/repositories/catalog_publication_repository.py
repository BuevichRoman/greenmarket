from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.infrastructure.models import CatalogPublication


class CatalogPublicationRepository:
    def __init__(self, session: Session):
        self.session = session

    def latest_version(self, seller_id: int) -> int:
        version = (
            self.session.query(func.max(CatalogPublication.version))
            .filter(CatalogPublication.seller_id == seller_id)
            .scalar()
        )
        return version or 0

    def exists_with_key(self, publication_key: str) -> bool:
        return (
            self.session.query(CatalogPublication)
            .filter(CatalogPublication.publication_key == publication_key)
            .first()
            is not None
        )

    def create(
        self,
        *,
        seller_id: int,
        version: int,
        publication_key: str,
        catalog_hash: str,
        published_by: int,
    ) -> CatalogPublication:
        publication = CatalogPublication(
            seller_id=seller_id,
            version=version,
            publication_key=publication_key,
            catalog_hash=catalog_hash,
            published_at=datetime.now(timezone.utc),
            published_by=published_by,
        )
        self.session.add(publication)
        self.session.flush()
        return publication

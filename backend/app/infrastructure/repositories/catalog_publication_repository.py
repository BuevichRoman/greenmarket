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

    def list_by_seller(self, seller_id: int) -> list[CatalogPublication]:
        return (
            self.session.query(CatalogPublication)
            .filter(CatalogPublication.seller_id == seller_id)
            .order_by(CatalogPublication.version.desc())
            .all()
        )

    def create(
        self,
        *,
        seller_id: int,
        version: int,
        publication_key: str,
        catalog_hash: str,
        published_by: int,
        created_count: int = 0,
        updated_count: int = 0,
        deactivated_count: int = 0,
    ) -> CatalogPublication:
        publication = CatalogPublication(
            seller_id=seller_id,
            version=version,
            publication_key=publication_key,
            catalog_hash=catalog_hash,
            published_at=datetime.now(timezone.utc),
            published_by=published_by,
            created_count=created_count,
            updated_count=updated_count,
            deactivated_count=deactivated_count,
        )
        self.session.add(publication)
        self.session.flush()
        return publication

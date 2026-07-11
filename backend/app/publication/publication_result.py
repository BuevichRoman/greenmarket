from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationResult:
    success: bool
    created_count: int
    updated_count: int
    deactivated_count: int
    publication_key: str | None
    catalog_hash: str | None

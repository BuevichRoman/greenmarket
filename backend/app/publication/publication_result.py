from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationResult:
    success: bool
    publication_id: int
    created_count: int
    updated_count: int
    deactivated_count: int
    publication_key: str
    catalog_hash: str
    mode: str = "prod"

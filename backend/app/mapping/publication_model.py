from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationProduct:
    seller_product_id: object | None
    seller_name: str
    product_group_name: str
    product_name: str | None
    price: float
    unit: str
    stock: float
    description: str | None
    attributes: str | None


@dataclass(frozen=True)
class PublicationMetadata:
    seller_id: int
    document_id: str | None
    document_version: str | None
    publication_key: str | None
    generated_at: object
    generated_by: str | None
    catalog_hash: str | None


@dataclass(frozen=True)
class PublicationModel:
    products: list[PublicationProduct]
    metadata: PublicationMetadata

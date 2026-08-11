from dataclasses import dataclass
from datetime import date


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
    photo_ids: list[int]
    # Шаблон 2.2. У книги шаблона 2.1 этих колонок нет физически, поэтому None
    # здесь — штатное значение, а не «продавец забыл заполнить».
    origin_country: str | None = None
    supply_date: date | None = None


@dataclass(frozen=True)
class PublicationMetadata:
    seller_id: int
    template_version: str | None
    template_id: str | None


@dataclass(frozen=True)
class PublicationModel:
    products: list[PublicationProduct]
    metadata: PublicationMetadata

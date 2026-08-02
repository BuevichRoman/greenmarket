from dataclasses import dataclass, field


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
    # Названия товаров, сохранённых в каталог продавца, но не показанных
    # покупателю из-за пустой колонки «Фото». Не счётчик, а список — продавцу
    # нужно знать, какие именно строки чинить (см. Catalog_Template.md).
    hidden_no_photo: list[str] = field(default_factory=list)

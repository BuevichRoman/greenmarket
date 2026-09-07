from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogChange:
    """Что путь публикации сделал с каталогом продавца.

    Общий слой публикации только записывает эти числа в CatalogPublication —
    как именно каталог пришёл в новое состояние, знает конкретный путь:
    книга сверяет присланные строки с существующими, Seller Admin работает
    с уже сохранённым состоянием.
    """

    created: int = 0
    updated: int = 0
    deactivated: int = 0
    # Товары, сохранённые в каталог, но покупателю не показанные из-за пустого
    # списка фотографий. Публикация при этом успешна (Publication_Model.md,
    # «Видимость предложения в Buyer Catalog»).
    hidden_no_photo: list[str] = field(default_factory=list)

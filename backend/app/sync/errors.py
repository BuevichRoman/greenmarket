class SyncSessionNotFoundError(Exception):
    """Сессии нет либо она принадлежит другому продавцу.

    Один класс на два случая намеренно — то же правило, что у позиций каталога:
    иначе перебором идентификаторов выясняется, какие сессии есть у соседа.
    """


class SyncSessionExpiredError(Exception):
    """Сессия истекла: старые решения к изменившемуся каталогу не применяются."""


class SheetCatalogMismatchError(Exception):
    """Отпечаток книги не совпал с отпечатком каталога — сверка не сделана."""


class BaselineNotReadyError(Exception):
    """У сессии ещё нет снимка."""

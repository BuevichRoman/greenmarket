class PublicationError(Exception):
    """Базовая ошибка Publication Service. Ошибки Parser/Validator/Mapper
    наружу не пробрасываются — Publication Service возвращает только
    собственные ошибки (задание PR-006)."""


class DuplicatePublicationError(PublicationError):
    """PublicationKey уже встречался в журнале публикаций (CatalogPublication) —
    повторная публикация того же документа отклоняется."""


class PublicationConflictError(PublicationError):
    """Строка каталога ссылается на SellerProductId, который не существует
    или принадлежит другому продавцу."""


class TestModeUnavailableError(PublicationError):
    """Рабочая книга запросила Mode=TEST, но на этом окружении не настроена
    тестовая БД (TEST_DB_NAME)."""

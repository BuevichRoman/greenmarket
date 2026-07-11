class MapperError(Exception):
    """Внутреннее нарушение контракта Mapper — Workbook должен быть
    провалидирован до вызова; нарушение здесь — Programming Error, не
    пользовательская ошибка."""

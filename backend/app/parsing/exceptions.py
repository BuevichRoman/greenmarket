class ParserError(Exception):
    """Файл источника не удалось прочитать. Общий тип для всех форматов (Excel/CSV/JSON/...),
    чтобы вызывающий код мог ловить одно исключение независимо от формата источника."""


class ExcelParserError(ParserError):
    """Excel-файл повреждён или не является валидным .xlsx."""


class GoogleSheetsParserError(ParserError):
    """Ошибка чтения Google Sheets через Service Account (сеть, таймаут, неожиданный ответ API)."""


class GoogleSheetsNotFoundError(GoogleSheetsParserError):
    """Таблица с указанным spreadsheet_id не существует."""


class GoogleSheetsAccessError(GoogleSheetsParserError):
    """Таблица не расшарена на Service Account GreenMarket."""

"""Разбор значений ячеек, которые два парсера отдают по-разному.

ExcelParser (openpyxl) возвращает дату как `datetime`, GoogleSheetsParser с
`valueRenderOption=UNFORMATTED_VALUE` — как число дней от 30.12.1899, а если
продавец ввёл дату в текстовую ячейку, придёт строка. Контракт RawWorkbook
одинаковый для обоих источников (см. GoogleSheetsParser), поэтому приводить
такие значения к одному типу обязан слой ниже валидации и маппинга — им обоим
нужен один и тот же ответ на вопрос «что в этой ячейке».
"""

from datetime import date, datetime, timedelta

# Excel/Sheets считают дни от 30.12.1899 (общая для них база с известным
# «багом 1900 года», уже заложенным в эту точку отсчёта).
_SERIAL_EPOCH = date(1899, 12, 30)

_TEXT_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")


def parse_supply_date(value: object) -> date | None:
    """Дата завоза партии из ячейки книги. Пустая ячейка — `None`, мусор —
    `ValueError` (текст ошибки наружу не идёт, сообщение продавцу формирует
    SemanticValidator)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # bool раньше int: True в ячейке — не «первое января 1900 года», а мусор.
    if isinstance(value, bool):
        raise ValueError(f"Логическое значение не является датой: {value!r}")
    if isinstance(value, (int, float)):
        return _SERIAL_EPOCH + timedelta(days=int(value))

    text = str(value).strip()
    if not text:
        return None
    for fmt in _TEXT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Не удалось разобрать дату: {value!r}")

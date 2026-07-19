from app.parsing.raw_workbook import RawWorkbook
from app.validation.structure_validator import SYSTEM_SHEET

_TEST_MODE_VALUES = {"TEST", "ТЕСТ"}


def read_mode(workbook: RawWorkbook) -> str:
    """Читает необязательное поле Mode из листа _System (переключатель
    бой/тест рабочей книги продавца). Отсутствует в листе или в самой книге —
    "prod": безопасное направление по умолчанию — опечатка не должна тихо
    увести боевую публикацию в тестовую БД. Совместимо с уже отправленными
    книгами без этого поля (ТЗ-010)."""
    system = next((s for s in workbook.sheets if s.name == SYSTEM_SHEET), None)
    if system is None:
        return "prod"
    values = {row[0]: (row[1] if len(row) > 1 else None) for row in system.rows if row}
    raw = values.get("Mode")
    if raw is None:
        return "prod"
    return "test" if str(raw).strip().upper() in _TEST_MODE_VALUES else "prod"

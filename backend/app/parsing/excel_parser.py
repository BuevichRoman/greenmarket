from pathlib import Path

import openpyxl

from app.parsing.exceptions import ExcelParserError
from app.parsing.raw_workbook import RawSheet, RawWorkbook


class ExcelParser:
    """Читает .xlsx в RawWorkbook. Ничего не знает о правилах GreenMarket —
    не проверяет листы/колонки/типы, не интерпретирует и не отбрасывает данные.
    Детерминирован: один и тот же файл всегда даёт один и тот же RawWorkbook.
    """

    def parse(self, path: Path) -> RawWorkbook:
        try:
            workbook = openpyxl.load_workbook(path, data_only=False)
        except Exception as exc:
            raise ExcelParserError(f"Не удалось прочитать Excel-файл: {path}") from exc

        sheets = [
            RawSheet(
                name=name,
                index=index,
                rows=[list(row) for row in workbook[name].iter_rows(values_only=True)],
            )
            for index, name in enumerate(workbook.sheetnames)
        ]
        return RawWorkbook(source=Path(path).name, sheets=sheets)

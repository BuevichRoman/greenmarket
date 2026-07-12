import hashlib
import json

from app.parsing.raw_workbook import RawWorkbook
from app.validation.structure_validator import CATALOG_SHEET


class HashCalculator:
    """Вычисляет CatalogHash — SHA-256 от содержимого листа «Каталог»
    (без заголовка). Вызывается сразу после Parser, до Validator (CR-001) —
    хеш должен зависеть только от содержимого документа, не от результата
    валидации.
    """

    def compute(self, workbook: RawWorkbook) -> str:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        rows = catalog.rows[1:] if catalog and catalog.rows else []
        payload = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

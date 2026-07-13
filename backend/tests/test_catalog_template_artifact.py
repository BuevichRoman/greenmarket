from pathlib import Path

from app.parsing.excel_parser import ExcelParser
from app.validation.structure_validator import StructureValidator

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_TEMPLATE_PATH = REPO_ROOT / "docs" / "02-domain" / "templates" / "catalog_template_v1.xlsx"


def test_master_template_file_exists():
    assert MASTER_TEMPLATE_PATH.is_file(), "Запусти `uv run python -m app.catalog_template.build` и закоммить файл"


def test_master_template_passes_structure_validation():
    # "Новый пустой шаблон" из акцептанс-критериев PR-008: 0 строк каталога,
    # структура должна быть валидна как есть, до заполнения продавцом.
    workbook = ExcelParser().parse(MASTER_TEMPLATE_PATH)

    result = StructureValidator().validate(workbook)

    assert result.is_valid, result.errors

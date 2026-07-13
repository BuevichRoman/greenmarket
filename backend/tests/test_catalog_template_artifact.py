from pathlib import Path

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.mapping.mapper import Mapper
from app.parsing.excel_parser import ExcelParser
from app.validation.business_validator import BusinessValidator
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
MASTER_TEMPLATE_PATH = REPO_ROOT / "docs" / "02-domain" / "templates" / "catalog_template_v1.xlsx"
EXAMPLES_DIR = REPO_ROOT / "docs" / "02-domain" / "templates" / "examples"
PARTIAL_EXAMPLE_PATH = EXAMPLES_DIR / "catalog_template_v1_partial.xlsx"
FULL_EXAMPLE_PATH = EXAMPLES_DIR / "catalog_template_v1_full.xlsx"


def _make_validator(session) -> Validator:
    return Validator(
        StructureValidator(),
        SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
        BusinessValidator(),
    )


def test_master_template_file_exists():
    assert MASTER_TEMPLATE_PATH.is_file(), "Запусти `uv run python -m app.catalog_template.build` и закоммить файл"


def test_master_template_passes_structure_validation():
    # "Новый пустой шаблон" из акцептанс-критериев PR-008: 0 строк каталога,
    # структура должна быть валидна как есть, до заполнения продавцом.
    workbook = ExcelParser().parse(MASTER_TEMPLATE_PATH)

    result = StructureValidator().validate(workbook)

    assert result.is_valid, result.errors


def test_partial_example_passes_full_pipeline(session):
    workbook = ExcelParser().parse(PARTIAL_EXAMPLE_PATH)

    result = _make_validator(session).validate(workbook)
    assert result.is_valid, result.errors

    model = Mapper().map(workbook, result, seller_id=1)
    assert len(model.products) == 2


def test_full_example_passes_full_pipeline(session):
    workbook = ExcelParser().parse(FULL_EXAMPLE_PATH)

    result = _make_validator(session).validate(workbook)
    assert result.is_valid, result.errors

    model = Mapper().map(workbook, result, seller_id=1)
    assert len(model.products) == 3
    assert model.products[2].product_name == "Прочее"

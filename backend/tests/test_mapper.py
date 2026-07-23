import ast
import inspect

import pytest

from app.mapping.errors import MapperError
from app.mapping.mapper import Mapper
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.errors import ValidationError, ValidationResult

CATALOG_HEADER = [
    "SellerProductId",
    "Название товара",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]

SYSTEM_ROWS = [
    ["TemplateVersion", "2.0"],
    ["TemplateId", "template-1"],
]


def make_workbook(catalog_rows: list[list[object]], extra_sheets: list[RawSheet] | None = None) -> RawWorkbook:
    sheets = [
        RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *catalog_rows]),
        RawSheet(name="_System", index=1, rows=SYSTEM_ROWS),
    ]
    if extra_sheets:
        sheets.extend(extra_sheets)
    return RawWorkbook(source="workbook.xlsx", sheets=sheets)


VALID_RESULT = ValidationResult(errors=[])


def test_maps_single_valid_row_into_publication_product():
    workbook = make_workbook([[1, "Ферма Иванова", "Овощи", "Морковь", 99.5, "кг", 10, "Свежая морковь", "Сорт: Нантская", "5"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert len(result.products) == 1
    product = result.products[0]
    assert product.seller_product_id == 1
    assert product.seller_name == "Ферма Иванова"
    assert product.product_group_name == "Овощи"
    assert product.product_name == "Морковь"
    assert product.price == 99.5
    assert product.unit == "кг"
    assert product.stock == 10
    assert product.description == "Свежая морковь"
    assert product.attributes == "Сорт: Нантская"
    assert product.photo_ids == [5]


def test_maps_multiple_catalog_rows_in_order():
    workbook = make_workbook(
        [
            [1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"],
            [2, "Ферма Б", "Фрукты", "Яблоко", 80, "кг", 20, None, None, "2;3"],
        ]
    )

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert [p.seller_product_id for p in result.products] == [1, 2]
    assert [p.product_name for p in result.products] == ["Морковь", "Яблоко"]
    assert [p.photo_ids for p in result.products] == [[1], [2, 3]]


def test_empty_catalog_maps_to_empty_products_list():
    workbook = make_workbook([])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.products == []


def test_ignores_reference_sheets_and_instruction_sheet():
    extra = [
        RawSheet(name="Товарные группы", index=2, rows=[["1", None, "Овощи"]]),
        RawSheet(name="Товарные позиции", index=3, rows=[["1", "1", "Морковь"]]),
        RawSheet(name="Инструкция", index=4, rows=[["свободный текст"]]),
    ]
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]], extra_sheets=extra)

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert len(result.products) == 1


def test_maps_system_sheet_and_seller_id_into_metadata():
    workbook = make_workbook([])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.metadata.seller_id == 42
    assert result.metadata.template_version == "2.0"
    assert result.metadata.template_id == "template-1"


def test_raises_mapper_error_when_validation_result_has_errors():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]])
    invalid_result = ValidationResult(errors=[ValidationError(sheet="Каталог", message="что-то не так")])

    with pytest.raises(MapperError):
        Mapper().map(workbook, invalid_result, seller_id=42)


def _imported_module_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_mapper_module_has_no_sqlalchemy_db_or_gateway_dependency():
    import app.mapping.mapper as mapper_module
    import app.mapping.publication_model as model_module

    forbidden_prefixes = ("sqlalchemy", "openpyxl", "app.infrastructure", "app.platform")
    for module in (mapper_module, model_module):
        for name in _imported_module_names(module):
            assert not name.startswith(forbidden_prefixes), f"{module.__name__} зависит от '{name}'"


def test_row_that_violates_the_validated_contract_raises_mapper_error_not_a_raw_exception():
    # Симулирует нарушение контракта «Workbook уже провалидирован» — Validator
    # такую строку никогда бы не пропустил, но если это всё же произошло, Mapper
    # обязан упасть предсказуемым MapperError, а не сырым TypeError/IndexError.
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", None, "кг", 5, None, None, "1"]])

    with pytest.raises(MapperError):
        Mapper().map(workbook, VALID_RESULT, seller_id=42)


def test_coerces_non_string_catalog_cells_to_str():
    # SemanticValidator проверяет "Название товара"/"Единица продажи" только
    # на непустоту (`if not value`), поэтому число вроде 777 проходит валидацию —
    # Mapper обязан привести их к единому строковому представлению.
    workbook = make_workbook([[1, 777, "Овощи", "Морковь", 50, 7, 5, None, None, "1"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    product = result.products[0]
    assert product.seller_name == "777"
    assert product.unit == "7"


def test_missing_catalog_sheet_raises_mapper_error():
    workbook = RawWorkbook(source="x.xlsx", sheets=[RawSheet(name="_System", index=0, rows=SYSTEM_ROWS)])

    with pytest.raises(MapperError):
        Mapper().map(workbook, VALID_RESULT, seller_id=42)


def test_missing_system_sheet_raises_mapper_error():
    workbook = RawWorkbook(source="x.xlsx", sheets=[RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER])])

    with pytest.raises(MapperError):
        Mapper().map(workbook, VALID_RESULT, seller_id=42)


def test_blank_string_cells_normalize_to_none():
    workbook = make_workbook([["", "Ферма А", "Овощи", "", 50, "кг", 5, "", "", ""]])

    product = Mapper().map(workbook, VALID_RESULT, seller_id=42).products[0]

    assert product.seller_product_id is None
    assert product.product_name is None
    assert product.description is None
    assert product.attributes is None
    assert product.photo_ids == []


def test_hand_built_fixture_workbook_actually_passes_real_structure_validator():
    # Держит тестовые данные Mapper в согласии с настоящим контрактом Validator —
    # если формат листов разойдётся, этот тест поймает это раньше, чем "Morкоvь".
    from app.validation.structure_validator import StructureValidator

    full_workbook = make_workbook(
        [[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]],
        extra_sheets=[
            RawSheet(name="Товарные группы", index=2, rows=[["ProductGroupId", "ParentProductGroupId", "Наименование"], [1, None, "Овощи"]]),
            RawSheet(name="Товарные позиции", index=3, rows=[["ProductId", "ProductGroupId", "Наименование"], [1, 1, "Морковь"]]),
            RawSheet(name="Инструкция", index=4, rows=[["свободный текст"]]),
        ],
    )

    assert StructureValidator().validate(full_workbook).is_valid


def test_maps_semicolon_separated_photo_ids_in_order():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "12;15;7"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.products[0].photo_ids == [12, 15, 7]


def test_empty_photo_cell_maps_to_empty_list():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, None]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.products[0].photo_ids == []

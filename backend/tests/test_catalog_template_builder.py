from app.catalog_template.build import build_workbook
from app.catalog_template.data import COLUMN_HINTS, GROUP_ROWS, PRODUCT_ROWS, TEMPLATE_ID, TEMPLATE_VERSION
from app.validation.structure_validator import (
    CATALOG_COLUMNS,
    CATALOG_SHEET,
    INSTRUCTION_SHEET,
    PRODUCT_GROUPS_SHEET,
    PRODUCTS_SHEET,
    REQUIRED_SHEETS,
    SUPPORTED_TEMPLATE_VERSIONS,
    SYSTEM_SHEET,
)


def test_column_hints_cover_exactly_the_catalog_columns():
    assert set(COLUMN_HINTS) == {column.name for column in CATALOG_COLUMNS}


def test_template_version_is_supported():
    assert TEMPLATE_VERSION in SUPPORTED_TEMPLATE_VERSIONS


def test_group_rows_and_product_rows_are_internally_consistent():
    group_ids = {row[0] for row in GROUP_ROWS}
    parent_ids = {row[1] for row in GROUP_ROWS if row[1] is not None}
    assert parent_ids <= group_ids  # каждый ParentProductGroupId существует среди ProductGroupId

    product_group_ids = {row[1] for row in PRODUCT_ROWS}
    assert product_group_ids <= group_ids  # каждый товар ссылается на существующую группу


def _sheet_values(ws):
    return [list(row) for row in ws.iter_rows(values_only=True)]


def test_all_required_sheets_present():
    wb = build_workbook()
    assert set(wb.sheetnames) == set(REQUIRED_SHEETS)


def test_catalog_header_matches_structure_validator_contract():
    wb = build_workbook()
    header = _sheet_values(wb[CATALOG_SHEET])[0]
    assert header == [column.name for column in CATALOG_COLUMNS]


def test_catalog_service_column_is_hidden():
    wb = build_workbook()
    assert wb[CATALOG_SHEET].column_dimensions["A"].hidden is True


def test_catalog_sheet_is_not_sheet_protected():
    # Продавец должен свободно добавлять/удалять/менять строки — служебные
    # листы защищены, рабочий лист «Каталог» нет (Catalog_Template.md).
    wb = build_workbook()
    assert wb[CATALOG_SHEET].protection.sheet is False


def test_reference_and_service_sheets_are_protected():
    wb = build_workbook()
    for name in (PRODUCT_GROUPS_SHEET, PRODUCTS_SHEET, INSTRUCTION_SHEET, SYSTEM_SHEET):
        assert wb[name].protection.sheet is True, f"{name} должен быть защищён от редактирования"


def test_system_sheet_is_hidden_and_matches_data_module():
    wb = build_workbook()
    ws = wb[SYSTEM_SHEET]
    assert ws.sheet_state == "hidden"
    values = dict(_sheet_values(ws))
    assert values == {"TemplateVersion": TEMPLATE_VERSION, "TemplateId": TEMPLATE_ID}


def test_reference_sheets_match_seed_data():
    wb = build_workbook()
    assert _sheet_values(wb[PRODUCT_GROUPS_SHEET])[1:] == GROUP_ROWS
    assert _sheet_values(wb[PRODUCTS_SHEET])[1:] == PRODUCT_ROWS


def test_every_catalog_header_cell_has_a_comment():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    for col_index in range(1, len(CATALOG_COLUMNS) + 1):
        assert ws.cell(row=1, column=col_index).comment is not None


def test_price_and_stock_columns_have_non_negative_validation():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    refs = [str(dv.sqref) for dv in ws.data_validations.dataValidation if dv.type == "decimal"]
    assert any(ref.startswith("E2") for ref in refs)
    assert any(ref.startswith("G2") for ref in refs)


def test_group_and_product_dropdowns_are_within_excel_inline_limit():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    list_validations = [dv for dv in ws.data_validations.dataValidation if dv.type == "list"]
    assert list_validations
    for dv in list_validations:
        assert len(dv.formula1) <= 255


def test_build_workbook_is_deterministic():
    first, second = build_workbook(), build_workbook()
    for name in first.sheetnames:
        assert _sheet_values(first[name]) == _sheet_values(second[name])


def test_build_workbook_accepts_prefilled_catalog_rows():
    row = [None, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]
    wb = build_workbook(catalog_rows=[row])
    assert _sheet_values(wb[CATALOG_SHEET])[1] == row

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


def test_group_product_price_stock_validations_hard_enforce():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    hard_enforced_ranges = {"C2", "D2", "E2", "G2"}
    for dv in ws.data_validations.dataValidation:
        sqref = str(dv.sqref)
        if any(sqref.startswith(prefix) for prefix in hard_enforced_ranges):
            assert dv.showErrorMessage is True, f"{sqref} должен блокировать некорректный ввод"


def test_unit_validation_is_soft_warning():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    unit_dv = next(dv for dv in ws.data_validations.dataValidation if str(dv.sqref).startswith("F2"))
    assert unit_dv.showErrorMessage is True
    assert unit_dv.errorStyle == "warning"


def test_product_dropdown_includes_prochee_placeholder():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    product_dv = next(dv for dv in ws.data_validations.dataValidation if str(dv.sqref).startswith("D2"))
    assert "Прочее" in product_dv.formula1


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
    row = [None, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "1"]
    wb = build_workbook(catalog_rows=[row])
    assert _sheet_values(wb[CATALOG_SHEET])[1] == row


def test_catalog_header_row_is_frozen():
    wb = build_workbook()
    assert wb[CATALOG_SHEET].freeze_panes == "A2"


def test_catalog_sheet_has_autofilter_over_full_data_range():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    last_row = max(ws.max_row, 1000)
    assert str(ws.auto_filter.ref) == f"A1:J{last_row}"


def test_catalog_columns_have_content_fitting_width():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    for col_index, column in enumerate(CATALOG_COLUMNS, start=1):
        letter = ws.cell(row=1, column=col_index).column_letter
        width = ws.column_dimensions[letter].width
        assert width is not None and width >= len(column.name) * 0.9, f"{column.name}: width={width}"

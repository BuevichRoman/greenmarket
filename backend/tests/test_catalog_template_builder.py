from app.catalog_template.data import COLUMN_HINTS, GROUP_ROWS, PRODUCT_ROWS, TEMPLATE_ID, TEMPLATE_VERSION
from app.validation.structure_validator import CATALOG_COLUMNS, SUPPORTED_TEMPLATE_VERSIONS


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

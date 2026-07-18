from app.catalog_template.build import build_workbook
from app.catalog_template.db_source import load_dropdown_names, load_group_rows, load_product_rows
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.validation.structure_validator import PRODUCT_GROUPS_SHEET, PRODUCTS_SHEET


def _sheet_values(ws):
    return [list(row) for row in ws.iter_rows(values_only=True)]


def test_load_group_rows_matches_active_product_groups(session):
    rows = load_group_rows(session)
    groups = ProductGroupRepository(session).list_active()
    assert rows == [[g.id, g.parent_id, g.name] for g in groups]


def test_load_product_rows_matches_active_products(session):
    rows = load_product_rows(session)
    products = ProductRepository(session).list_active()
    assert rows == [[p.id, p.product_group_id, p.name] for p in products]


def test_load_dropdown_names_includes_prochee_placeholder(session):
    group_rows = load_group_rows(session)
    product_rows = load_product_rows(session)
    group_names, product_names = load_dropdown_names(group_rows, product_rows)

    assert group_names == [row[2] for row in group_rows]
    assert product_names == [row[2] for row in product_rows] + ["Прочее"]


def test_build_workbook_with_db_rows_reflects_current_database(session):
    group_rows = load_group_rows(session)
    product_rows = load_product_rows(session)
    group_names, product_names = load_dropdown_names(group_rows, product_rows)

    wb = build_workbook(group_rows=group_rows, product_rows=product_rows, group_names=group_names, product_names=product_names)

    assert _sheet_values(wb[PRODUCT_GROUPS_SHEET])[1:] == group_rows
    assert _sheet_values(wb[PRODUCTS_SHEET])[1:] == product_rows

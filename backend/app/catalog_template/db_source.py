"""Альтернатива статическим `_GROUP_DEFS`/`_PRODUCT_DEFS` из data.py: читает
актуальные ProductGroup/Product из БД, чтобы шаблон при пересборке не мог
разойтись с реальным каталогом (см. docstring data.py — два источника правды).

Используется только когда build.py явно запущен с `--from-db`; поведение
по умолчанию (build_workbook() без аргументов, статические данные) не
меняется — существующие тесты и сборка нормативного .xlsx не затронуты.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository


def load_group_rows(session: Session) -> list[list[object]]:
    groups = ProductGroupRepository(session).list_active()
    return [[g.id, g.parent_id, g.name] for g in groups]


def load_product_rows(session: Session) -> list[list[object]]:
    products = ProductRepository(session).list_active()
    return [[p.id, p.product_group_id, p.name] for p in products]


def load_dropdown_names(
    group_rows: list[list[object]], product_rows: list[list[object]]
) -> tuple[list[str], list[str]]:
    group_names = [row[2] for row in group_rows]
    product_names = [row[2] for row in product_rows] + ["Прочее"]
    return group_names, product_names

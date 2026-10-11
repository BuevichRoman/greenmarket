from decimal import Decimal

import pytest
from sqlalchemy import text

from app.api.v1.stock_operations import StockOperationRequest


def test_request_rejects_non_positive_quantity():
    with pytest.raises(Exception):
        StockOperationRequest(
            idempotency_key="test-key",
            operation="SALE",
            seller_product_id=1,
            quantity=Decimal("0"),
            unit="кг",
        )


def test_request_rejects_unknown_fields():
    with pytest.raises(Exception):
        StockOperationRequest(
            idempotency_key="test-key",
            operation="SALE",
            seller_product_id=1,
            quantity=Decimal("1"),
            unit="кг",
            seller_id=9,
        )


def test_request_requires_known_operation():
    with pytest.raises(Exception):
        StockOperationRequest(
            idempotency_key="test-key",
            operation="STOCK_SET",
            seller_product_id=1,
            quantity=Decimal("1"),
            unit="кг",
        )


def test_stock_operation_migration_contract_exists():
    # Static guard: database schema must preserve idempotency and audit fields.
    from pathlib import Path
    migration = Path(__file__).resolve().parents[2] / "database" / "migrations" / "022_create_seller_stock_operation.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "UNIQUE (seller_id, idempotency_key)" in sql
    assert "stock_before" in sql and "stock_after" in sql
    assert "FOREIGN KEY (seller_product_id)" in sql

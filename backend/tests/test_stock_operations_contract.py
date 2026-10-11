from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.v1.stock_operations import StockOperationRequest, _same_payload


def make_request(**overrides):
    values = {
        "idempotency_key": "test-key",
        "operation": "SALE",
        "seller_product_id": 1,
        "quantity": Decimal("1.250"),
        "unit": "кг",
    }
    values.update(overrides)
    return StockOperationRequest(**values)


def test_request_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        make_request(quantity=Decimal("0"))


@pytest.mark.parametrize("quantity", [Decimal("-1"), Decimal("1.2345")])
def test_request_rejects_negative_or_over_precision_quantity(quantity):
    with pytest.raises(ValidationError):
        make_request(quantity=quantity)


def test_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make_request(seller_id=9)


def test_request_requires_known_operation():
    with pytest.raises(ValidationError):
        make_request(operation="STOCK_SET")


@pytest.mark.parametrize("unit", [" кг ", "кг"])
def test_request_trims_unit(unit):
    assert make_request(unit=unit).unit == "кг"

def test_request_trims_idempotency_key():
    assert make_request(idempotency_key="  test-key  ").idempotency_key == "test-key"


def test_request_rejects_blank_idempotency_key():
    with pytest.raises(ValidationError):
        make_request(idempotency_key="   ")


def test_request_rejects_blank_unit():
    with pytest.raises(ValidationError):
        make_request(unit="   ")


def test_same_idempotency_payload_compares_decimal_and_unit_semantics():
    request = make_request(quantity=Decimal("1.25"), unit="КГ")
    existing = {
        "seller_product_id": 1,
        "operation": "SALE",
        "quantity": Decimal("1.250"),
        "unit": "кг",
    }
    assert _same_payload(existing, request)


def test_same_idempotency_key_with_different_payload_is_not_a_replay():
    request = make_request(seller_product_id=2)
    existing = {
        "seller_product_id": 1,
        "operation": "SALE",
        "quantity": Decimal("1.250"),
        "unit": "кг",
    }
    assert not _same_payload(existing, request)


def test_stock_operation_migration_contract_exists():
    # Static guard: database schema must preserve idempotency and audit fields.
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "022_create_seller_stock_operation.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "UNIQUE (seller_id, idempotency_key)" in sql
    assert "stock_before" in sql and "stock_after" in sql
    assert "FOREIGN KEY (seller_id) REFERENCES Seller(id)" in sql
    assert "FOREIGN KEY (seller_product_id)" in sql
    assert "CHECK (quantity > 0)" in sql

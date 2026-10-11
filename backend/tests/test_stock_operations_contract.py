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
    assert "seller_id BIGINT UNSIGNED NOT NULL" in sql
    assert "seller_product_id BIGINT UNSIGNED NOT NULL" in sql
    assert "stock_before" in sql and "stock_after" in sql
    assert "FOREIGN KEY (seller_id) REFERENCES Seller(id)" in sql
    assert "FOREIGN KEY (seller_product_id)" in sql
    assert "CHECK (quantity > 0)" in sql


# These focused endpoint tests exercise the transaction decision path without
# claiming to replace MySQL integration/concurrency tests.
from copy import deepcopy
from datetime import datetime

from app.api.v1.stock_operations import create_stock_operation
from app.publication.seller_access import SellerAccess


class FakeResult:
    def __init__(self, row=None, lastrowid=None):
        self.row = row
        self.lastrowid = lastrowid

    def first(self):
        return self.row

    def mappings(self):
        return self

    def one(self):
        if self.row is None:
            raise AssertionError("Expected one row")
        return self.row


class FakeStockSession:
    def __init__(self, *, stock=Decimal("10.000"), unit="кг", active=True, product_seller_id=7):
        self.seller_active = active
        self.product = {
            "id": 10,
            "seller_id": product_seller_id,
            "stock": stock,
            "unit": unit,
            "version": 1,
        }
        self.operations = []
        self.next_id = 1
        self.snapshot = None

    def _begin(self):
        if self.snapshot is None:
            self.snapshot = (
                deepcopy(self.product),
                deepcopy(self.operations),
                self.next_id,
            )

    def execute(self, statement, params=None):
        self._begin()
        sql = str(statement)
        params = params or {}

        if "current_catalog_version" in sql and "FROM Seller" in sql and "is_active" in sql:
            return FakeResult((self.seller_active, 1, None))

        if "FROM SellerStockOperation" in sql and "WHERE seller_id = :seller_id" in sql:
            row = next((
                deepcopy(op) for op in self.operations
                if op["seller_id"] == params["seller_id"]
                and op["idempotency_key"] == params["key"]
            ), None)
            return FakeResult(row)

        if "FROM SellerStockOperation WHERE id = :id" in sql:
            row = next((deepcopy(op) for op in self.operations if op["id"] == params["id"]), None)
            return FakeResult(row)

        if "FROM SellerProduct" in sql and "FOR UPDATE" in sql:
            row = self.product
            if row is None or row["id"] != params["product_id"] or row["seller_id"] != params["seller_id"]:
                return FakeResult(None)
            return FakeResult(deepcopy(row))

        if sql.lstrip().startswith("UPDATE SellerProduct"):
            self.product["stock"] = Decimal(str(params["stock_after"]))
            self.product["version"] += 1
            return FakeResult()

        if sql.lstrip().startswith("INSERT INTO SellerStockOperation"):
            row = {
                "id": self.next_id,
                "seller_id": params["seller_id"],
                "seller_product_id": params["product_id"],
                "idempotency_key": params["key"],
                "operation": params["operation"],
                "quantity": Decimal(params["quantity"]),
                "unit": params["unit"],
                "stock_before": Decimal(params["stock_before"]),
                "stock_after": Decimal(params["stock_after"]),
                "created_at": datetime(2026, 10, 11, 12, 0, 0),
            }
            self.operations.append(row)
            self.next_id += 1
            return FakeResult(lastrowid=row["id"])

        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.snapshot = None

    def rollback(self):
        if self.snapshot is not None:
            self.product, self.operations, self.next_id = self.snapshot
            self.snapshot = None


def call_operation(session, request):
    return create_stock_operation(
        request=request,
        session=session,
        access=SellerAccess(seller_id=7, published_by=1, name="Seller"),
    )


def test_sale_updates_stock_and_duplicate_replay_does_not_apply_twice():
    session = FakeStockSession()
    request = make_request(operation="SALE", quantity=Decimal("2"))
    result = call_operation(session, request)
    assert result["stock_before"] == "10.000"
    assert result["stock_after"] == "8.000"
    assert session.product["stock"] == Decimal("8")
    assert len(session.operations) == 1

    replay = call_operation(session, request)
    assert replay["operation_id"] == result["operation_id"]
    assert session.product["stock"] == Decimal("8")
    assert len(session.operations) == 1


def test_incoming_increases_stock_and_records_operation():
    session = FakeStockSession()
    result = call_operation(session, make_request(operation="INCOMING", quantity=Decimal("1.5")))
    assert result["stock_before"] == "10.000"
    assert result["stock_after"] == "11.500"
    assert session.product["stock"] == Decimal("11.500")
    assert session.operations[0]["operation"] == "INCOMING"


def test_sale_over_available_stock_does_not_write():
    session = FakeStockSession(stock=Decimal("1.000"))
    result = call_operation(session, make_request(quantity=Decimal("2")))
    assert result.status_code == 409
    assert session.product["stock"] == Decimal("1.000")
    assert session.operations == []


def test_unit_mismatch_does_not_write():
    session = FakeStockSession(unit="л")
    result = call_operation(session, make_request(unit="кг"))
    assert result.status_code == 422
    assert session.product["stock"] == Decimal("10.000")
    assert session.operations == []


def test_reusing_key_with_different_payload_conflicts_without_second_write():
    session = FakeStockSession()
    first = call_operation(session, make_request(quantity=Decimal("1")))
    assert first["stock_after"] == "9.000"
    second = call_operation(session, make_request(quantity=Decimal("2")))
    assert second.status_code == 409
    assert session.product["stock"] == Decimal("9")
    assert len(session.operations) == 1


def test_inactive_seller_cannot_register_stock_operation():
    session = FakeStockSession(active=False)
    result = call_operation(session, make_request())
    assert result.status_code == 403
    assert session.product["stock"] == Decimal("10.000")
    assert session.operations == []


def test_incoming_that_exceeds_decimal_capacity_does_not_write():
    session = FakeStockSession(stock=Decimal("999999999.999"))
    result = call_operation(session, make_request(operation="INCOMING", quantity=Decimal("0.001")))
    assert result.status_code == 422
    assert session.product["stock"] == Decimal("999999999.999")
    assert session.operations == []


def test_reused_key_with_nonexistent_different_product_is_conflict_not_not_found():
    session = FakeStockSession()
    call_operation(session, make_request())
    result = call_operation(session, make_request(seller_product_id=999))
    assert result.status_code == 409
    assert session.product["stock"] == Decimal("9.000")
    assert len(session.operations) == 1


def test_foreign_seller_product_is_not_mutated():
    session = FakeStockSession(product_seller_id=8)
    result = call_operation(session, make_request())
    assert result.status_code == 404
    assert session.product["stock"] == Decimal("10.000")
    assert session.operations == []



@pytest.fixture
def mysql_stock_context(committing_session):
    """Real MySQL fixture; the outer transaction is rolled back by conftest."""
    from sqlalchemy import text

    session = committing_session
    user_id = session.execute(
        text("INSERT INTO users (name) VALUES (:name)"),
        {"name": "GM stock operation integration test"},
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"),
        {"user_id": user_id},
    ).lastrowid
    product_id = session.execute(
        text("""
            INSERT INTO SellerProduct (seller_id, seller_name, stock, unit)
            VALUES (:seller_id, :seller_name, :stock, :unit)
        """),
        {
            "seller_id": seller_id,
            "seller_name": "Товар для проверки складских операций",
            "stock": Decimal("10.000"),
            "unit": "кг",
        },
    ).lastrowid
    return session, seller_id, user_id, product_id


def test_mysql_sale_and_idempotent_replay_change_stock_once(mysql_stock_context):
    from sqlalchemy import text

    session, seller_id, user_id, product_id = mysql_stock_context
    request = make_request(
        idempotency_key=f"gm-stock-test-{seller_id}",
        operation="SALE",
        seller_product_id=product_id,
        quantity=Decimal("2.000"),
        unit="кг",
    )
    access = SellerAccess(seller_id=seller_id, published_by=user_id, name="Integration seller")

    first = create_stock_operation(request=request, session=session, access=access)
    assert first["stock_before"] == "10.000"
    assert first["stock_after"] == "8.000"
    assert session.execute(
        text("SELECT stock FROM SellerProduct WHERE id = :id"),
        {"id": product_id},
    ).scalar_one() == Decimal("8.000")

    replay = create_stock_operation(request=request, session=session, access=access)
    assert replay["operation_id"] == first["operation_id"]
    assert session.execute(
        text("SELECT stock FROM SellerProduct WHERE id = :id"),
        {"id": product_id},
    ).scalar_one() == Decimal("8.000")
    assert session.execute(
        text("SELECT COUNT(*) FROM SellerStockOperation WHERE seller_id = :seller_id AND idempotency_key = :key"),
        {"seller_id": seller_id, "key": request.idempotency_key},
    ).scalar_one() == 1

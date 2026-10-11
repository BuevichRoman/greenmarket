from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.schemas import error_response
from app.api.v1.seller import get_seller_bearer_access, seller_access_denied
from app.infrastructure.database import get_session
from app.platform.seller_gateway import SellerGateway
from app.publication.seller_access import SellerAccess

router = APIRouter(prefix="/api/v1/seller", tags=["seller-stock-operations"])


class StockOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=64)
    operation: Literal["SALE", "INCOMING"]
    seller_product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(min_length=1, max_length=30)

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_unit(cls, value):
        return value.strip() if isinstance(value, str) else value


def _operation_result(row) -> dict:
    return {
        "operation_id": int(row["id"]),
        "operation": row["operation"],
        "seller_product_id": int(row["seller_product_id"]),
        "quantity": str(row["quantity"]),
        "unit": row["unit"],
        "stock_before": str(row["stock_before"]),
        "stock_after": str(row["stock_after"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _find_by_key(session: Session, seller_id: int, key: str):
    return session.execute(text("""
        SELECT id, seller_id, seller_product_id, idempotency_key, operation,
               quantity, unit, stock_before, stock_after, created_at
        FROM SellerStockOperation
        WHERE seller_id = :seller_id AND idempotency_key = :key
    """), {"seller_id": seller_id, "key": key}).mappings().first()


def _same_payload(existing, request: StockOperationRequest) -> bool:
    return (
        int(existing["seller_product_id"]) == request.seller_product_id
        and existing["operation"] == request.operation
        and Decimal(existing["quantity"]) == request.quantity
        and existing["unit"].strip().casefold() == request.unit.strip().casefold()
    )


def _existing_response(session: Session, seller_id: int, request: StockOperationRequest):
    existing = _find_by_key(session, seller_id, request.idempotency_key)
    if existing is None:
        return None
    session.rollback()
    if not _same_payload(existing, request):
        return error_response(409, "IDEMPOTENCY_KEY_REUSED", "Ключ операции уже использован с другими данными")
    return _operation_result(existing)


@router.post("/stock-operations", status_code=201)
def create_stock_operation(
    request: StockOperationRequest,
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
):
    """Register a sale or incoming delivery atomically and idempotently."""
    if access is None:
        return seller_access_denied()

    seller_status = SellerGateway(session).get_status(access.seller_id)
    if seller_status is None:
        return error_response(404, "SELLER_NOT_FOUND", "Продавец не найден")
    if not seller_status.is_active:
        return error_response(403, "SELLER_INACTIVE", "Учётная запись продавца неактивна")

    try:
        # Fast path: a replay must return the original result even if its changed
        # payload points to a nonexistent product. Recheck after row locking too.
        replay = _existing_response(session, access.seller_id, request)
        if replay is not None:
            return replay

        product = session.execute(text("""
            SELECT id, seller_id, stock, unit, version
            FROM SellerProduct
            WHERE id = :product_id AND seller_id = :seller_id
            FOR UPDATE
        """), {"product_id": request.seller_product_id, "seller_id": access.seller_id}).mappings().first()
        if product is None:
            session.rollback()
            return error_response(404, "SELLER_PRODUCT_NOT_FOUND", "Позиция каталога не найдена")

        # Another request may have committed while this request waited for the
        # product lock. The unique constraint remains the final cross-product guard.
        replay = _existing_response(session, access.seller_id, request)
        if replay is not None:
            return replay

        product_unit = str(product["unit"]).strip()
        if product_unit.casefold() != request.unit.casefold():
            session.rollback()
            return error_response(422, "UNIT_MISMATCH", f"Единица товара — {product_unit}; преобразование не выполняется")

        stock_before = Decimal(str(product["stock"]))
        if request.operation == "SALE":
            stock_after = stock_before - request.quantity
            if stock_after < 0:
                session.rollback()
                return error_response(409, "INSUFFICIENT_STOCK", "Недостаточно остатка для продажи")
        else:
            stock_after = stock_before + request.quantity

        session.execute(text("""
            UPDATE SellerProduct
            SET stock = :stock_after, version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = :product_id AND seller_id = :seller_id
        """), {
            "stock_after": stock_after,
            "product_id": request.seller_product_id,
            "seller_id": access.seller_id,
        })
        inserted = session.execute(text("""
            INSERT INTO SellerStockOperation
                (seller_id, seller_product_id, idempotency_key, operation, quantity, unit, stock_before, stock_after)
            VALUES
                (:seller_id, :product_id, :key, :operation, :quantity, :unit, :stock_before, :stock_after)
        """), {
            "seller_id": access.seller_id,
            "product_id": request.seller_product_id,
            "key": request.idempotency_key,
            "operation": request.operation,
            "quantity": request.quantity,
            "unit": product_unit,
            "stock_before": stock_before,
            "stock_after": stock_after,
        })
        operation_id = inserted.lastrowid
        session.commit()
        row = session.execute(text("""
            SELECT id, seller_id, seller_product_id, idempotency_key, operation,
                   quantity, unit, stock_before, stock_after, created_at
            FROM SellerStockOperation WHERE id = :id
        """), {"id": operation_id}).mappings().one()
        return _operation_result(row)
    except IntegrityError:
        session.rollback()
        existing = _find_by_key(session, access.seller_id, request.idempotency_key)
        if existing is not None:
            if _same_payload(existing, request):
                return _operation_result(existing)
            return error_response(409, "IDEMPOTENCY_KEY_REUSED", "Ключ операции уже использован с другими данными")
        return error_response(409, "STOCK_OPERATION_CONFLICT", "Операция конфликтует с текущим состоянием каталога")
    except Exception:
        session.rollback()
        raise

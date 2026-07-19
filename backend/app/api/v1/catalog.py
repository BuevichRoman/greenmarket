import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import (
    ProductDetailResponse,
    ProductGroupItem,
    ProductGroupsResponse,
    ProductListItem,
    ProductListResponse,
    SellerOfferItem,
)
from app.api.v1.schemas import error_response
from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/groups", response_model=ProductGroupsResponse)
def list_groups(session: Session = Depends(get_session)) -> ProductGroupsResponse:
    use_case = CatalogUseCase(session)
    groups = use_case.list_groups()
    return ProductGroupsResponse(groups=[ProductGroupItem(**group) for group in groups])


@router.get("/products", response_model=ProductListResponse)
def list_products(
    group_id: int | None = None,
    search: str | None = None,
    sort: Literal["name", "price"] = "name",
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> ProductListResponse:
    use_case = CatalogUseCase(session)
    items, total = use_case.list_products(group_id=group_id, search=search, sort=sort, page=page, limit=limit)
    return ProductListResponse(
        products=[ProductListItem(**item) for item in items],
        page=page,
        limit=limit,
        total=total,
    )


def _not_found(message: str) -> JSONResponse:
    return error_response(404, "NOT_FOUND", message)


@router.get("/products/{product_id}", response_model=ProductDetailResponse)
def get_product(product_id: int, session: Session = Depends(get_session)) -> ProductDetailResponse | JSONResponse:
    use_case = CatalogUseCase(session)
    product = use_case.get_product(product_id)
    if product is None:
        return _not_found(f"Товар {product_id} не найден или недоступен")
    return ProductDetailResponse(
        id=product["id"],
        name=product["name"],
        description=product["description"],
        offers=[SellerOfferItem(**offer) for offer in product["offers"]],
    )

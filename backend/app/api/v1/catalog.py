import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import (
    ProductGroupItem,
    ProductGroupsResponse,
    ProductListItem,
    ProductListResponse,
)
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

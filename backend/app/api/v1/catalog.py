import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import ProductGroupItem, ProductGroupsResponse
from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/groups", response_model=ProductGroupsResponse)
def list_groups(session: Session = Depends(get_session)) -> ProductGroupsResponse:
    use_case = CatalogUseCase(session)
    groups = use_case.list_groups()
    return ProductGroupsResponse(groups=[ProductGroupItem(**group) for group in groups])

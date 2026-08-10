import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import (
    MapMarketItem,
    MapMarketListResponse,
    MarketSellerItem,
    MarketSellerListResponse,
    ProductDetailResponse,
    ProductGroupItem,
    ProductGroupsResponse,
    ProductListItem,
    ProductListResponse,
    SellerCardResponse,
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
        group_id=product["group_id"],
        group_name=product["group_name"],
        offers=[SellerOfferItem(**offer) for offer in product["offers"]],
    )


@router.get("/markets", response_model=MapMarketListResponse)
def list_markets(session: Session = Depends(get_session)) -> MapMarketListResponse:
    """Точки для экрана «Карта»: рынки и лавки с координатами."""
    markets = CatalogUseCase(session).list_markets()
    return MapMarketListResponse(markets=[MapMarketItem(**market) for market in markets])


@router.get("/markets/{market_id}/sellers", response_model=MarketSellerListResponse)
def list_market_sellers(
    market_id: int, session: Session = Depends(get_session)
) -> MarketSellerListResponse | JSONResponse:
    """Продавцы точки — то, что покупатель видит, нажав на пин."""
    sellers = CatalogUseCase(session).list_market_sellers(market_id)
    if sellers is None:
        return _not_found(f"Место торговли {market_id} не найдено или недоступно")
    return MarketSellerListResponse(sellers=[MarketSellerItem(**seller) for seller in sellers])


@router.get("/sellers/{seller_id}", response_model=SellerCardResponse)
def get_seller_card(seller_id: int, session: Session = Depends(get_session)) -> SellerCardResponse | JSONResponse:
    card = CatalogUseCase(session).get_seller_card(seller_id)
    if card is None:
        return _not_found(f"Продавец {seller_id} не найден или недоступен")
    return SellerCardResponse(**card)

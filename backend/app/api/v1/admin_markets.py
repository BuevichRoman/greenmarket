"""Admin API справочника рынков (миграция 017).

Отдельный роутер от admin_catalog.py: там единый товарный справочник
платформы, здесь — места торговли. Аутентификация общая.

Рынки ведёт администратор, а не продавец: название, адрес и координаты
принадлежат рынку, и один и тот же рынок обслуживает сотни продавцов
(Seller_Profile.md, §3). Продавец рынок только выбирает — см.
`GET /api/v1/seller/markets`.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess
from app.api.v1.admin import admin_access_denied, get_admin_access
from app.api.v1.admin_schemas import (
    MarketCreateRequest,
    MarketListResponse,
    MarketSummary,
    MarketUpdateRequest,
)
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session
from app.infrastructure.models import Market
from app.infrastructure.repositories.market_repository import MarketRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _market_not_found(market_id: int) -> JSONResponse:
    return error_response(404, "MARKET_NOT_FOUND", f"Место торговли {market_id} не найдено")


def _summary(market: Market) -> MarketSummary:
    return MarketSummary(
        id=market.id,
        name=market.name,
        type=market.type,
        address=market.address,
        latitude=market.latitude,
        longitude=market.longitude,
        is_active=market.is_active,
    )


@router.get("/markets", response_model=MarketListResponse)
def list_markets(
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> MarketListResponse | JSONResponse:
    """Включая закрытые: закрытый рынок иначе нечем вернуть в работу."""
    if access is None:
        return admin_access_denied()

    return MarketListResponse(markets=[_summary(m) for m in MarketRepository(session).list_all()])


@router.post("/markets", response_model=MarketSummary, status_code=201)
def create_market(
    request: MarketCreateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> MarketSummary | JSONResponse:
    if access is None:
        return admin_access_denied()

    market = MarketRepository(session).create(
        name=request.name,
        type=request.type,
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
    )
    session.commit()
    return _summary(market)


@router.put("/markets/{market_id}", response_model=MarketSummary)
def update_market(
    market_id: int,
    request: MarketUpdateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> MarketSummary | JSONResponse:
    if access is None:
        return admin_access_denied()

    market = MarketRepository(session).find_by_id(market_id)
    if market is None:
        return _market_not_found(market_id)

    # По присланным ключам, а не по значениям: `{"latitude": null}` снимает
    # координату, отсутствие ключа оставляет её как есть.
    for field in request.model_fields_set:
        setattr(market, field, getattr(request, field))

    session.commit()
    return _summary(market)

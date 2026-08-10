from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.publications import get_seller_access_resolver
from app.api.v1.schemas import error_response
from app.api.v1.seller_schemas import (
    MarketListResponse,
    MarketOption,
    SellerActivationRequest,
    SellerActivationResponse,
    SellerProfileResponse,
    SellerProfileUpdateRequest,
    SellerProfileUpdateResponse,
    SellerStatusResponse,
)
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.market_repository import MarketRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.seller_gateway import SellerGateway
from app.profile.errors import ProfileValidationError, SellerNotFoundError
from app.profile.seller_profile_service import SellerProfileService
from app.publication.seller_activation import activate_seller

router = APIRouter(prefix="/api/v1/seller", tags=["seller"])


@router.get("/catalog", response_model=SellerStatusResponse)
def get_seller_catalog(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerStatusResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    status = SellerGateway(session).get_status(access.seller_id)
    if status is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {access.seller_id} не найден")

    publications = CatalogPublicationRepository(session).list_by_seller(access.seller_id)
    last_published_at = publications[0].published_at if publications else None

    return SellerStatusResponse(
        seller_id=access.seller_id,
        is_active=status.is_active,
        current_catalog_version=status.current_catalog_version,
        published_product_count=SellerProductRepository(session).count_published(access.seller_id),
        last_published_at=last_published_at,
    )


@router.post("/activate", response_model=SellerActivationResponse)
def activate(
    request: SellerActivationRequest,
    session: Session = Depends(get_session),
) -> SellerActivationResponse | JSONResponse:
    access_token = activate_seller(request.activation_code, spreadsheet_id=request.spreadsheet_id, session=session)
    if access_token is None:
        return error_response(400, "INVALID_ACTIVATION_CODE", "Код активации недействителен.")

    session.commit()
    return SellerActivationResponse(access_token=access_token)


def _profile_response(seller_id: int, *, session: Session) -> SellerProfileResponse | JSONResponse:
    # find_list_row, а не get_status: имя и is_active приезжают одной строкой,
    # а имя из токена брать нельзя — оно есть только у этого вызывающего.
    seller = SellerGateway(session).find_list_row(seller_id)
    if seller is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    service = SellerProfileService(session)
    profile = service.read(seller_id)
    return SellerProfileResponse(
        seller_id=seller_id,
        name=seller.name,
        status="ACTIVE" if seller.is_active else "INACTIVE",
        suggested_phone=service.suggested_phone(seller_id),
        **profile,
    )


@router.get("/markets", response_model=MarketListResponse)
def list_markets(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> MarketListResponse | JSONResponse:
    """Справочник мест торговли для выпадающего списка в форме профиля —
    и рынки, и отдельно стоящие лавки.

    Только открытые точки: закрытую выбрать нельзя, её и не предлагаем.
    Токен требуется, как и у остального Seller API, — справочник живёт в
    кабинете продавца, а не в публичном каталоге.
    """
    if resolve_access(access_token) is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    markets = MarketRepository(session).list_active()
    return MarketListResponse(
        markets=[MarketOption(id=m.id, name=m.name, type=m.type, address=m.address) for m in markets]
    )


@router.get("/profile", response_model=SellerProfileResponse)
def get_seller_profile(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")
    return _profile_response(access.seller_id, session=session)


@router.put("/profile", response_model=SellerProfileUpdateResponse)
def update_seller_profile(
    request: SellerProfileUpdateRequest,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileUpdateResponse | JSONResponse:
    access = resolve_access(request.access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        changed = SellerProfileService(session).apply(
            access.seller_id,
            request.changed_values(),
            # published_by — платформенный users.id_user продавца: поле названо
            # по первому потребителю, публикациям, но хранит именно id пользователя.
            author_user_id=access.published_by,
            author_role="SELLER",
        )
    except SellerNotFoundError as exc:
        return error_response(404, "SELLER_NOT_FOUND", str(exc))
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return SellerProfileUpdateResponse(changed=changed)

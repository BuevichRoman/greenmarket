from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.publications import get_seller_access_resolver
from app.api.v1.schemas import error_response
from app.api.v1.seller_schemas import (
    SellerActivationRequest,
    SellerActivationResponse,
    SellerProfileResponse,
    SellerProfileUpdateRequest,
    SellerProfileUpdateResponse,
    SellerStatusResponse,
)
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.seller_gateway import SellerGateway
from app.profile.errors import ProfileValidationError
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


def _profile_response(seller_id: int, name: str, session: Session) -> SellerProfileResponse | JSONResponse:
    status = SellerGateway(session).get_status(seller_id)
    if status is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    service = SellerProfileService(session)
    profile = service.read(seller_id)
    return SellerProfileResponse(
        seller_id=seller_id,
        name=name,
        status="ACTIVE" if status.is_active else "INACTIVE",
        suggested_phone=service.suggested_phone(seller_id),
        **profile,
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
    return _profile_response(access.seller_id, access.name, session)


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
            author_user_id=access.published_by,
            author_role="SELLER",
        )
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return SellerProfileUpdateResponse(changed=changed)

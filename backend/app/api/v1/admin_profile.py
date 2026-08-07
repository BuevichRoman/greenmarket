"""Админская часть профиля продавца: правка полей и лента изменений.

Лента — сознательно pull, а не push: механизма уведомлений (почта, мессенджер)
в системе не существует, и коллега-архитектор 06.08.2026 принял ленту в Admin
Cabinet как достаточную для Stage 1.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess
from app.api.v1.admin import admin_access_denied, get_admin_access
from app.api.v1.admin_schemas import (
    AdminSellerProfileResponse,
    AdminSellerProfileUpdateRequest,
    AdminSellerProfileUpdateResponse,
    SellerProfileChangeFeedResponse,
    SellerProfileChangeItem,
)
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session
from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.platform.seller_gateway import SellerGateway
from app.profile.errors import ProfileValidationError, SellerNotFoundError
from app.profile.seller_profile_service import SellerProfileService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/sellers/{seller_id}/profile", response_model=AdminSellerProfileResponse)
def get_seller_profile(
    seller_id: int,
    session: Session = Depends(get_session),
    access: AdminAccess | None = Depends(get_admin_access),
) -> AdminSellerProfileResponse | JSONResponse:
    """Профиль продавца для формы редактирования в Admin Cabinet. Другого
    способа прочитать его у администратора нет: продавцовский GET требует
    access_token, список продавцов профиля не содержит, а покупательская
    карточка скрывает деактивированных — то есть ровно тех, кого чаще всего и
    правят.
    """
    if access is None:
        return admin_access_denied()

    # find_list_row, а не get_status: имя и is_active приезжают одной строкой.
    seller = SellerGateway(session).find_list_row(seller_id)
    if seller is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    return AdminSellerProfileResponse(
        seller_id=seller_id,
        name=seller.name,
        status="ACTIVE" if seller.is_active else "INACTIVE",
        **SellerProfileService(session).read(seller_id),
    )


@router.put("/sellers/{seller_id}/profile", response_model=AdminSellerProfileUpdateResponse)
def update_seller_profile(
    seller_id: int,
    request: AdminSellerProfileUpdateRequest,
    session: Session = Depends(get_session),
    access: AdminAccess | None = Depends(get_admin_access),
) -> AdminSellerProfileUpdateResponse | JSONResponse:
    if access is None:
        return admin_access_denied()

    try:
        changed = SellerProfileService(session).apply(
            seller_id,
            request.changed_values(),
            author_user_id=access.user_id,
            author_role="ADMIN",
        )
    except SellerNotFoundError as exc:
        # В отличие от Seller API, здесь seller_id приходит из пути, а не из
        # токена, поэтому несуществующий продавец — реальная ситуация, а не
        # недостижимая ветка.
        return error_response(404, "SELLER_NOT_FOUND", str(exc))
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return AdminSellerProfileUpdateResponse(seller_id=seller_id, changed=changed)


@router.get("/profile-changes", response_model=SellerProfileChangeFeedResponse)
def list_profile_changes(
    limit: int = Query(default=50, ge=1, le=200),
    after_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    access: AdminAccess | None = Depends(get_admin_access),
) -> SellerProfileChangeFeedResponse | JSONResponse:
    if access is None:
        return admin_access_denied()

    repository = SellerProfileChangeRepository(session)
    changes = repository.list_recent(limit=limit, after_id=after_id)
    names = SellerGateway(session).list_seller_names([change.seller_id for change in changes])

    return SellerProfileChangeFeedResponse(
        changes=[
            SellerProfileChangeItem(
                id=change.id,
                seller_id=change.seller_id,
                seller_name=names.get(change.seller_id, ""),
                field=change.field,
                old_value=change.old_value,
                new_value=change.new_value,
                author_user_id=change.author_user_id,
                author_role=change.author_role,
                created_at=change.created_at,
            )
            for change in changes
        ],
        total=repository.count_recent(after_id=after_id),
    )

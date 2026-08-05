from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess, resolve_admin_access
from app.admin.admin_activation import activate_admin
from app.admin.seller_onboarding import SellerAlreadyExistsError, UserNotFoundError, onboard_seller
from app.api.v1.admin_schemas import (
    AdminActivationRequest,
    AdminActivationResponse,
    AdminIdentityResponse,
    SellerActivationCodeResponse,
    SellerListResponse,
    SellerOnboardingRequest,
    SellerSummary,
)
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session
from app.platform.seller_gateway import SellerGateway
from app.publication.seller_activation import issue_activation_code

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_BEARER_PREFIX = "bearer "


def get_admin_access(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> AdminAccess | None:
    """Достаёт администратора из заголовка `Authorization: Bearer <token>`.

    В отличие от продавца токен не принимается в query-строке: она целиком
    попадает в access.log nginx, а права администратора шире — модерация всего
    каталога, а не одного продавца.
    """
    if authorization is None or not authorization.lower().startswith(_BEARER_PREFIX):
        return None
    return resolve_admin_access(authorization[len(_BEARER_PREFIX):].strip(), session)


def admin_access_denied() -> JSONResponse:
    return error_response(401, "ADMIN_ACCESS_DENIED", "Токен доступа администратора недействителен")


@router.post("/activate", response_model=AdminActivationResponse)
def activate(
    request: AdminActivationRequest,
    session: Session = Depends(get_session),
) -> AdminActivationResponse | JSONResponse:
    access_token = activate_admin(request.activation_code, session=session)
    if access_token is None:
        return error_response(400, "INVALID_ACTIVATION_CODE", "Код активации недействителен.")

    session.commit()
    return AdminActivationResponse(access_token=access_token)


@router.get("/me", response_model=AdminIdentityResponse)
def me(access: AdminAccess | None = Depends(get_admin_access)) -> AdminIdentityResponse | JSONResponse:
    if access is None:
        return admin_access_denied()
    return AdminIdentityResponse(admin_id=access.admin_id, user_id=access.user_id)


@router.post("/sellers", response_model=SellerActivationCodeResponse, status_code=201)
def create_seller(
    request: SellerOnboardingRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> SellerActivationCodeResponse | JSONResponse:
    """Подключить пользователя платформы как продавца: создать учётную запись
    и выдать код активации одной операцией."""
    if access is None:
        return admin_access_denied()

    try:
        result = onboard_seller(request.user_id, session=session)
    except UserNotFoundError as error:
        return error_response(404, "USER_NOT_FOUND", str(error))
    except SellerAlreadyExistsError as error:
        return error_response(409, "SELLER_ALREADY_EXISTS", str(error))

    session.commit()
    return SellerActivationCodeResponse(seller_id=result.seller_id, activation_code=result.activation_code)


@router.get("/sellers", response_model=SellerListResponse)
def list_sellers(
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> SellerListResponse | JSONResponse:
    """Список подключённых продавцов с основной информацией (Admin_MVP.md,
    экран 4). Без него администратор создаёт продавца и теряет его из виду."""
    if access is None:
        return admin_access_denied()

    rows = SellerGateway(session).list_all()
    return SellerListResponse(sellers=[SellerSummary(**vars(row)) for row in rows])


def _set_seller_active(seller_id: int, *, is_active: bool, session: Session) -> SellerSummary | JSONResponse:
    gateway = SellerGateway(session)
    if gateway.find_list_row(seller_id) is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    gateway.set_active(seller_id, is_active=is_active)
    session.commit()
    return SellerSummary(**vars(gateway.find_list_row(seller_id)))


@router.put("/sellers/{seller_id}/activate", response_model=SellerSummary)
def activate_seller(
    seller_id: int,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> SellerSummary | JSONResponse:
    """Вернуть продавца в активное состояние. Последняя опубликованная версия
    каталога снова доступна покупателям без повторной публикации."""
    if access is None:
        return admin_access_denied()
    return _set_seller_active(seller_id, is_active=True, session=session)


@router.put("/sellers/{seller_id}/deactivate", response_model=SellerSummary)
def deactivate_seller(
    seller_id: int,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> SellerSummary | JSONResponse:
    """Временная деактивация: каталог скрывается от покупателей, публикации,
    SellerProduct и история сохраняются."""
    if access is None:
        return admin_access_denied()
    return _set_seller_active(seller_id, is_active=False, session=session)


@router.post("/sellers/{seller_id}/activation-code", response_model=SellerActivationCodeResponse)
def reissue_activation_code(
    seller_id: int,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> SellerActivationCodeResponse | JSONResponse:
    """Перевыпустить код активации — продавец потерял код или не успел
    воспользоваться им до истечения TTL. Предыдущий код перестаёт действовать."""
    if access is None:
        return admin_access_denied()

    activation_code = issue_activation_code(seller_id, session=session)
    if activation_code is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    session.commit()
    return SellerActivationCodeResponse(seller_id=seller_id, activation_code=activation_code)


@router.delete("/sellers/{seller_id}/activation-code", status_code=204)
def revoke_activation_code(
    seller_id: int,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
):
    """Отозвать невостребованный код активации. Уже выданный рабочий токен не
    трогает — это другая операция (деактивация продавца)."""
    if access is None:
        return admin_access_denied()

    gateway = SellerGateway(session)
    if gateway.get_status(seller_id) is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    gateway.clear_activation_code(seller_id)
    session.commit()
    return Response(status_code=204)

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess, resolve_admin_access
from app.admin.admin_activation import activate_admin
from app.api.v1.admin_schemas import AdminActivationRequest, AdminActivationResponse, AdminIdentityResponse
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session

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

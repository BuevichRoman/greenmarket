import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.photos_schemas import PhotoUploadResponse
from app.api.v1.schemas import error_response
from app.core.config import settings
from app.infrastructure.database import get_session
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import PhotoStorage
from app.publication.seller_access import resolve_seller_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/photos", tags=["photos"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def get_photo_storage():
    """Переопределяется в тестах фейковым S3-клиентом. По умолчанию `None` —
    endpoint строит настоящий PhotoStorage (см. upload_photo ниже), тот же
    паттерн, что get_google_sheets_parser_resource в publications.py."""
    return None


def get_seller_access_resolver():
    return resolve_seller_access


@router.post("", response_model=PhotoUploadResponse, status_code=201)
def upload_photo(
    access_token: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    storage=Depends(get_photo_storage),
    resolve_access=Depends(get_seller_access_resolver),
):
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        return error_response(422, "UNSUPPORTED_CONTENT_TYPE", f"Недопустимый тип файла '{file.content_type}'")

    file_bytes = file.file.read()
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        return error_response(413, "FILE_TOO_LARGE", "Файл превышает допустимый размер 10 МБ")

    photo_storage = storage if storage is not None else PhotoStorage(bucket=settings.s3_bucket)
    s3_key = photo_storage.upload(file_bytes, file.content_type)
    photo_id = PhotoGateway(session).create(s3_key=s3_key, seller_id=access.seller_id)
    session.commit()

    logger.info("Фото загружено: seller_id=%s photo_id=%s", access.seller_id, photo_id)
    return PhotoUploadResponse(photo_id=photo_id)

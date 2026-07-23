import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.photos_schemas import PhotoInfo, PhotoListResponse, PhotoUploadResponse
from app.api.v1.schemas import error_response
from app.core.config import settings
from app.infrastructure.database import get_session
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import PhotoStorage, build_photo_url
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


def get_seller_access_resolver(session: Session = Depends(get_session)):
    return lambda access_token: resolve_seller_access(access_token, session)


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

    # Читаем не больше лимита + 1 байт, чтобы никогда не держать в памяти
    # произвольно большое тело запроса до проверки размера.
    file_bytes = file.file.read(_MAX_FILE_SIZE_BYTES + 1)
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        return error_response(413, "FILE_TOO_LARGE", "Файл превышает допустимый размер 10 МБ")

    photo_storage = (
        storage
        if storage is not None
        else PhotoStorage(
            bucket=settings.s3_bucket, region=settings.s3_region, endpoint_url=settings.s3_endpoint_url or None
        )
    )
    try:
        s3_key = photo_storage.upload(file_bytes, file.content_type)
    except Exception as exc:
        logger.exception("Ошибка загрузки фото в S3: seller_id=%s error=%s", access.seller_id, exc)
        return error_response(500, "PHOTO_STORAGE_ERROR", "Не удалось загрузить фото")

    # Если вставка в БД или commit упадут после успешной загрузки в S3, объект
    # в S3 останется осиротевшим — в Stage 1 нет задачи очистки, это принятый компромисс.
    photo_id = PhotoGateway(session).create(s3_key=s3_key, seller_id=access.seller_id)
    session.commit()

    logger.info("Фото загружено: seller_id=%s photo_id=%s", access.seller_id, photo_id)
    return PhotoUploadResponse(photo_id=photo_id)


@router.get("", response_model=PhotoListResponse)
def list_photos(
    ids: str,
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
):
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        photo_ids = [int(part.strip()) for part in ids.split(",") if part.strip()]
    except ValueError:
        return error_response(422, "INVALID_IDS", f"'{ids}' содержит нечисловой идентификатор фото")

    rows = PhotoGateway(session).list_by_ids_and_seller(photo_ids, access.seller_id)
    photos = [
        PhotoInfo(
            photo_id=photo_id,
            url=build_photo_url(
                s3_key, bucket=settings.s3_bucket, region=settings.s3_region, public_base_url=settings.s3_public_base_url
            ),
        )
        for photo_id, s3_key in rows
    ]
    return PhotoListResponse(photos=photos)

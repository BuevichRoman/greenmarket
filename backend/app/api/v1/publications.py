import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.schemas import PublicationRequest, PublicationResponse, ValidationErrorDetail, error_response
from app.application.publication_use_case import PublicationUseCase, PublicationValidationError
from app.infrastructure.database import get_session, get_test_session
from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, ParserError
from app.publication.errors import DuplicatePublicationError, PublicationConflictError, TestModeUnavailableError
from app.publication.seller_access import resolve_seller_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/publications", tags=["publications"])


def get_google_sheets_parser_resource():
    """Переопределяется в тестах (`app.dependency_overrides`) фейковым Sheets-ресурсом —
    см. `backend/tests/test_google_sheets_parser.py::FakeSheetsResource`.
    По умолчанию `None` → PublicationUseCase строит настоящий клиент Google Sheets API."""
    return None


def get_seller_access_resolver():
    """Переопределяется в тестах фейковым резолвером токенов —
    см. `backend/tests/test_publications_api.py::override_seller_access`."""
    return resolve_seller_access


@router.post("", response_model=PublicationResponse)
def create_publication(
    request: PublicationRequest,
    session: Session = Depends(get_session),
    test_session: Session | None = Depends(get_test_session),
    parser_resource=Depends(get_google_sheets_parser_resource),
    resolve_access=Depends(get_seller_access_resolver),
):
    access = resolve_access(request.access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        spreadsheet_id = request.resolve_spreadsheet_id()
    except ValueError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    logger.info("Публикация начата: seller_id=%s spreadsheet_id=%s", access.seller_id, spreadsheet_id)

    try:
        use_case = PublicationUseCase(session, test_session, parser_resource=parser_resource)
        result = use_case.publish(spreadsheet_id, seller_id=access.seller_id, published_by=access.published_by)
    except TestModeUnavailableError as exc:
        return error_response(422, "TEST_MODE_UNAVAILABLE", str(exc))
    except PublicationValidationError as exc:
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Каталог не прошёл валидацию",
            details=[
                ValidationErrorDetail(sheet=e.sheet, row=e.row, column=e.column, message=e.message)
                for e in exc.validation_result.errors
            ],
        )
    except DuplicatePublicationError as exc:
        return error_response(409, "DUPLICATE_PUBLICATION", str(exc))
    except PublicationConflictError as exc:
        return error_response(409, "PUBLICATION_CONFLICT", str(exc))
    except GoogleSheetsNotFoundError as exc:
        return error_response(404, "SHEET_NOT_FOUND", str(exc))
    except GoogleSheetsAccessError as exc:
        return error_response(403, "SHEET_ACCESS_DENIED", str(exc))
    except ParserError as exc:
        logger.warning("Ошибка Google Sheets API: seller_id=%s error=%s", access.seller_id, exc)
        return error_response(500, "GOOGLE_API_ERROR", "Ошибка при обращении к Google Sheets API")
    except Exception as exc:
        logger.exception("Внутренняя ошибка при публикации: seller_id=%s error=%s", access.seller_id, exc)
        return error_response(500, "INTERNAL_ERROR", "Внутренняя ошибка сервера")

    logger.info(
        "Публикация завершена: seller_id=%s publication_id=%s created=%s updated=%s deactivated=%s",
        access.seller_id, result.publication_id, result.created_count, result.updated_count, result.deactivated_count,
    )
    return PublicationResponse(
        success=result.success,
        publication_id=result.publication_id,
        created=result.created_count,
        updated=result.updated_count,
        deactivated=result.deactivated_count,
        message="Публикация выполнена успешно",
        mode=result.mode,
    )

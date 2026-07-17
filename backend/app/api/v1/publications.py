import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.schemas import ErrorDetail, ErrorResponse, PublicationRequest, PublicationResponse, ValidationErrorDetail
from app.application.publication_use_case import PublicationUseCase, PublicationValidationError
from app.infrastructure.database import get_session
from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, ParserError
from app.publication.errors import DuplicatePublicationError, PublicationConflictError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/publications", tags=["publications"])


def get_google_sheets_parser_resource():
    """Переопределяется в тестах (`app.dependency_overrides`) фейковым Sheets-ресурсом —
    см. `backend/tests/test_google_sheets_parser.py::FakeSheetsResource`.
    По умолчанию `None` → PublicationUseCase строит настоящий клиент Google Sheets API."""
    return None


def _error(status_code: int, code: str, message: str, details: list[ValidationErrorDetail] | None = None) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@router.post("", response_model=PublicationResponse)
def create_publication(
    request: PublicationRequest,
    session: Session = Depends(get_session),
    parser_resource=Depends(get_google_sheets_parser_resource),
):
    try:
        spreadsheet_id = request.resolve_spreadsheet_id()
    except ValueError as exc:
        return _error(422, "VALIDATION_ERROR", str(exc))

    logger.info("Публикация начата: seller_id=%s spreadsheet_id=%s", request.seller_id, spreadsheet_id)

    try:
        use_case = PublicationUseCase(session, parser_resource=parser_resource)
        result = use_case.publish(spreadsheet_id, seller_id=request.seller_id, published_by=request.published_by)
    except PublicationValidationError as exc:
        return _error(
            422,
            "VALIDATION_ERROR",
            "Каталог не прошёл валидацию",
            details=[
                ValidationErrorDetail(sheet=e.sheet, row=e.row, column=e.column, message=e.message)
                for e in exc.validation_result.errors
            ],
        )
    except DuplicatePublicationError as exc:
        return _error(409, "DUPLICATE_PUBLICATION", str(exc))
    except PublicationConflictError as exc:
        return _error(409, "PUBLICATION_CONFLICT", str(exc))
    except GoogleSheetsNotFoundError as exc:
        return _error(404, "SHEET_NOT_FOUND", str(exc))
    except GoogleSheetsAccessError as exc:
        return _error(403, "SHEET_ACCESS_DENIED", str(exc))
    except ParserError as exc:
        logger.warning("Ошибка Google Sheets API: seller_id=%s error=%s", request.seller_id, exc)
        return _error(500, "GOOGLE_API_ERROR", "Ошибка при обращении к Google Sheets API")
    except Exception as exc:
        logger.exception("Внутренняя ошибка при публикации: seller_id=%s error=%s", request.seller_id, exc)
        return _error(500, "INTERNAL_ERROR", "Внутренняя ошибка сервера")

    logger.info(
        "Публикация завершена: seller_id=%s publication_id=%s created=%s updated=%s deactivated=%s",
        request.seller_id, result.publication_id, result.created_count, result.updated_count, result.deactivated_count,
    )
    return PublicationResponse(
        success=result.success,
        publication_id=result.publication_id,
        created=result.created_count,
        updated=result.updated_count,
        deactivated=result.deactivated_count,
        message="Публикация выполнена успешно",
    )

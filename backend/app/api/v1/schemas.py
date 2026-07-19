import re

from fastapi.responses import JSONResponse
from pydantic import BaseModel

_SHEET_URL_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


class PublicationRequest(BaseModel):
    access_token: str
    sheet_url: str | None = None
    spreadsheet_id: str | None = None

    def resolve_spreadsheet_id(self) -> str:
        if self.spreadsheet_id:
            return self.spreadsheet_id
        if self.sheet_url:
            match = _SHEET_URL_PATTERN.search(self.sheet_url)
            if match:
                return match.group(1)
        raise ValueError("Не указан sheet_url или spreadsheet_id")


class PublicationResponse(BaseModel):
    success: bool
    publication_id: int
    created: int
    updated: int
    deactivated: int
    message: str
    mode: str


class ValidationErrorDetail(BaseModel):
    sheet: str
    message: str
    row: int | None = None
    column: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[ValidationErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_response(
    status_code: int, code: str, message: str, details: list[ValidationErrorDetail] | None = None
) -> JSONResponse:
    """Единый error-envelope для всех эндпоинтов /api/v1 — раньше catalog.py и
    publications.py собирали его каждый своим локальным хелпером."""
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status_code, content=payload.model_dump())

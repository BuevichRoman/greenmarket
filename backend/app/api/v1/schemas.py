import re

from pydantic import BaseModel

_SHEET_URL_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


class PublicationRequest(BaseModel):
    seller_id: int
    published_by: int
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


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[str] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail

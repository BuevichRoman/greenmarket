import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, GoogleSheetsParserError
from app.parsing.raw_workbook import RawSheet, RawWorkbook

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class GoogleSheetsParser:
    """Читает Google Sheets в RawWorkbook через Service Account — тот же
    контракт, что ExcelParser (CR-001): не вычисляет PublicationKey/CatalogHash,
    только читает структуру таблицы. `valueRenderOption=UNFORMATTED_VALUE`
    обязателен — иначе числа (цена/остаток) придут строками, что нарушит
    эквивалентность с ExcelParser (openpyxl отдаёт float).

    `resource` — необязательный уже собранный клиент Sheets API (googleapiclient
    resource или тестовый дублёр с тем же интерфейсом `.spreadsheets()`); если не
    передан, строится настоящий клиент из Service Account credentials.
    """

    def __init__(self, resource=None, timeout: float | None = None):
        self.timeout = timeout if timeout is not None else settings.google_sheets_timeout_seconds
        self._service = resource if resource is not None else self._build_service()

    def _build_service(self):
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=_SCOPES
        )
        http = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=self.timeout))
        return build("sheets", "v4", http=http, cache_discovery=False)

    def parse(self, spreadsheet_id: str) -> RawWorkbook:
        try:
            return self._parse(spreadsheet_id)
        except GoogleSheetsParserError:
            raise
        except HttpError as exc:
            raise self._map_http_error(exc, spreadsheet_id) from exc
        except Exception as exc:
            raise GoogleSheetsParserError(f"Ошибка при обращении к Google Sheets API ('{spreadsheet_id}'): {exc}") from exc

    def _parse(self, spreadsheet_id: str) -> RawWorkbook:
        spreadsheets = self._service.spreadsheets()
        metadata = spreadsheets.get(spreadsheetId=spreadsheet_id).execute(num_retries=0)
        sheet_titles = [sheet["properties"]["title"] for sheet in metadata["sheets"]]

        response = spreadsheets.values().batchGet(
            spreadsheetId=spreadsheet_id, ranges=sheet_titles, valueRenderOption="UNFORMATTED_VALUE"
        ).execute(num_retries=0)

        sheets = [
            RawSheet(name=title, index=index, rows=value_range.get("values", []))
            for index, (title, value_range) in enumerate(zip(sheet_titles, response["valueRanges"]))
        ]
        return RawWorkbook(source=spreadsheet_id, sheets=sheets)

    def _map_http_error(self, exc: HttpError, spreadsheet_id: str) -> GoogleSheetsParserError:
        status = exc.resp.status if exc.resp else None
        if status == 404:
            return GoogleSheetsNotFoundError(f"Таблица '{spreadsheet_id}' не найдена")
        if status == 403:
            return GoogleSheetsAccessError(f"Нет доступа к таблице '{spreadsheet_id}' — расшарьте на Service Account")
        return GoogleSheetsParserError(f"Ошибка Google Sheets API при чтении '{spreadsheet_id}': {exc}")

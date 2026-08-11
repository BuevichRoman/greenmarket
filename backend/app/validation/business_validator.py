from app.parsing.raw_workbook import RawWorkbook
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_COLUMNS, CATALOG_SHEET

# Индексы выведены из CATALOG_COLUMNS — единственного источника истины порядка
# колонок, как и в Mapper. Своя копия порядка здесь разошлась бы при следующей
# правке шаблона.
_COLUMN_INDEX = {column.name: index for index, column in enumerate(CATALOG_COLUMNS)}
_COL_SELLER_PRODUCT_ID = _COLUMN_INDEX["SellerProductId"]
_COL_SELLER_SKU = _COLUMN_INDEX["Артикул продавца"]


class BusinessValidator:
    """Проверяет отсутствие дублей ключей сопоставления внутри каталога:
    `SellerProductId` (выдан сервером) и «Артикул продавца» (выдан продавцом).
    Дубль любого из них означал бы, что две строки книги претендуют на один
    товар: при публикации они схлопнулись бы в одну позицию, и продавец молча
    потерял бы товар.

    PublicationKey больше не проверяется здесь (CR-001,
    docs/06-development/adr/0002-static-google-sheets-template.md) — документ
    Google Sheets не содержит PublicationKey, сверять его с состоянием
    продавца стало нечем.
    """

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        if catalog is None or len(catalog.rows) < 2:
            return ValidationResult(errors=[])

        return ValidationResult(
            errors=[
                *self._duplicates(catalog, _COL_SELLER_PRODUCT_ID, "SellerProductId"),
                *self._duplicates(catalog, _COL_SELLER_SKU, "Артикул продавца"),
            ]
        )

    def _duplicates(self, catalog, column_index: int, column_name: str) -> list[ValidationError]:
        rows_by_value: dict[str, list[int]] = {}
        for row_number, row in enumerate(catalog.rows[1:], start=2):
            value = row[column_index] if column_index < len(row) else None
            if value is None or value == "":
                continue
            # Ключ строкой: Sheets отдаёт артикул «1001» числом, а «PROD-1001»
            # строкой — для продавца это одно поле, и дубль обязан находиться
            # независимо от того, как ячейку разобрал Sheets API.
            rows_by_value.setdefault(str(value), []).append(row_number)

        return [
            ValidationError(
                sheet=catalog.name,
                column=column_name,
                message=f"{column_name} {value} дублируется в строках {rows}",
            )
            for value, rows in rows_by_value.items()
            if len(rows) > 1
        ]

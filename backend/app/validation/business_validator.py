from app.parsing.raw_workbook import RawWorkbook
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET

_COL_SELLER_PRODUCT_ID = 0


class BusinessValidator:
    """Проверяет отсутствие дублей SellerProductId внутри каталога.

    PublicationKey больше не проверяется здесь (CR-001,
    docs/06-development/adr/0002-static-google-sheets-template.md) — документ
    Google Sheets не содержит PublicationKey, сверять его с состоянием
    продавца стало нечем.
    """

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        return ValidationResult(errors=self._validate_seller_product_id_uniqueness(workbook))

    def _validate_seller_product_id_uniqueness(self, workbook: RawWorkbook) -> list[ValidationError]:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        if catalog is None or len(catalog.rows) < 2:
            return []

        rows_by_id: dict[object, list[int]] = {}
        for row_number, row in enumerate(catalog.rows[1:], start=2):
            seller_product_id = row[_COL_SELLER_PRODUCT_ID] if _COL_SELLER_PRODUCT_ID < len(row) else None
            if seller_product_id is None or seller_product_id == "":
                continue
            rows_by_id.setdefault(seller_product_id, []).append(row_number)

        return [
            ValidationError(
                sheet=catalog.name,
                column="SellerProductId",
                message=f"SellerProductId {seller_product_id} дублируется в строках {rows}",
            )
            for seller_product_id, rows in rows_by_id.items()
            if len(rows) > 1
        ]

from app.parsing.raw_workbook import RawWorkbook
from app.platform.seller_gateway import SellerGateway
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET, SYSTEM_SHEET

_COL_SELLER_PRODUCT_ID = 0


class BusinessValidator:
    """Проверяет бизнес-правила, требующие знания о состоянии продавца и
    согласованности каталога целиком: актуальность PublicationKey (через
    SellerGateway — Seller не мапится как ORM, см. app/platform/seller_gateway.py)
    и отсутствие дублей SellerProductId. Не проверяет структуру документа
    или значения отдельных ячеек (StructureValidator/SemanticValidator).

    Проверка целостности документа (CatalogHash) в этот PR не входит —
    алгоритм и область хеширования требуют отдельного согласования с
    коллегой (см. kwork/timeline.md, п.38), чтобы совпадать с будущей
    генерацией документа в Publication Service.
    """

    def __init__(self, seller_gateway: SellerGateway):
        self.seller_gateway = seller_gateway

    def validate(self, workbook: RawWorkbook, seller_id: int) -> ValidationResult:
        errors: list[ValidationError] = []
        errors += self._validate_publication_key(workbook, seller_id)
        errors += self._validate_seller_product_id_uniqueness(workbook)
        return ValidationResult(errors=errors)

    def _validate_publication_key(self, workbook: RawWorkbook, seller_id: int) -> list[ValidationError]:
        system_sheet = next((sheet for sheet in workbook.sheets if sheet.name == SYSTEM_SHEET), None)
        if system_sheet is None:
            return []

        document_key = next((row[1] for row in system_sheet.rows if row and row[0] == "PublicationKey"), None)
        if document_key is None:
            return []

        current_key = self.seller_gateway.get_current_publication_key(seller_id)
        if document_key != current_key:
            return [
                ValidationError(
                    sheet=system_sheet.name,
                    message="PublicationKey устарел или недействителен — скачайте новую редакцию каталога",
                )
            ]
        return []

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

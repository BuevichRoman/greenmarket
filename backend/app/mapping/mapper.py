from app.mapping.errors import MapperError
from app.mapping.publication_model import PublicationMetadata, PublicationModel, PublicationProduct
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.errors import ValidationResult
from app.validation.structure_validator import CATALOG_COLUMNS, CATALOG_SHEET, SYSTEM_FIELDS, SYSTEM_SHEET

# Индексы выведены из CATALOG_COLUMNS (structure_validator.py) — единственный
# источник истины порядка колонок Excel Template v1.0, не отдельная копия.
_COLUMN_INDEX = {column.name: index for index, column in enumerate(CATALOG_COLUMNS)}
_COL_SELLER_PRODUCT_ID = _COLUMN_INDEX["SellerProductId"]
_COL_SELLER_NAME = _COLUMN_INDEX["Наименование продавца"]
_COL_PRODUCT_GROUP = _COLUMN_INDEX["Товарная группа GreenMarket"]
_COL_PRODUCT = _COLUMN_INDEX["Товарная позиция GreenMarket"]
_COL_PRICE = _COLUMN_INDEX["Цена"]
_COL_UNIT = _COLUMN_INDEX["Единица продажи"]
_COL_STOCK = _COLUMN_INDEX["Остаток"]
_COL_DESCRIPTION = _COLUMN_INDEX["Описание"]
_COL_ATTRIBUTES = _COLUMN_INDEX["Дополнительные характеристики"]


def _cell(row: list[object], index: int) -> object:
    return row[index] if index < len(row) else None


def _blank_to_none(value: object) -> object:
    return None if value == "" else value


def _to_str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


class Mapper:
    """Преобразует провалидированный RawWorkbook в PublicationModel —
    внутреннюю модель Publication Service, независимую от Excel и
    SQLAlchemy. Никакой предметной логики (поиск Product/ProductGroup,
    обращение к БД/Gateway) — это уже сделано Validator; здесь только
    преобразование структуры данных.
    """

    def map(self, workbook: RawWorkbook, validation_result: ValidationResult, seller_id: int) -> PublicationModel:
        if not validation_result.is_valid:
            raise MapperError("Mapper вызван с невалидным ValidationResult — Workbook должен быть провалидирован до вызова Mapper")

        catalog = self._find_sheet(workbook, CATALOG_SHEET)
        system = self._find_sheet(workbook, SYSTEM_SHEET)

        products = [self._map_row(row_number, row) for row_number, row in enumerate(catalog.rows[1:], start=2)]
        metadata = self._map_metadata(system, seller_id)

        return PublicationModel(products=products, metadata=metadata)

    def _find_sheet(self, workbook: RawWorkbook, name: str) -> RawSheet:
        sheet = next((s for s in workbook.sheets if s.name == name), None)
        if sheet is None:
            raise MapperError(f"В RawWorkbook отсутствует обязательный лист '{name}' — Validator должен был это отклонить")
        return sheet

    def _map_row(self, row_number: int, row: list[object]) -> PublicationProduct:
        try:
            return PublicationProduct(
                seller_product_id=_blank_to_none(_cell(row, _COL_SELLER_PRODUCT_ID)),
                seller_name=str(_cell(row, _COL_SELLER_NAME)),
                product_group_name=str(_cell(row, _COL_PRODUCT_GROUP)),
                product_name=_to_str_or_none(_blank_to_none(_cell(row, _COL_PRODUCT))),
                price=float(_cell(row, _COL_PRICE)),
                unit=str(_cell(row, _COL_UNIT)),
                stock=float(_cell(row, _COL_STOCK)),
                description=_to_str_or_none(_blank_to_none(_cell(row, _COL_DESCRIPTION))),
                attributes=_to_str_or_none(_blank_to_none(_cell(row, _COL_ATTRIBUTES))),
            )
        except (TypeError, ValueError) as exc:
            # Workbook уже должен быть провалидирован — сюда попадает только
            # нарушение этого контракта (Programming Error), поэтому наружу
            # уходит предсказуемый MapperError, а не сырой TypeError/ValueError.
            raise MapperError(f"Строка {row_number} листа «Каталог» не соответствует контракту провалидированного каталога: {exc}") from exc

    def _map_metadata(self, system: RawSheet, seller_id: int) -> PublicationMetadata:
        values = {row[0]: (row[1] if len(row) > 1 else None) for row in system.rows if row and row[0] in SYSTEM_FIELDS}
        return PublicationMetadata(
            seller_id=seller_id,
            template_version=values.get("TemplateVersion"),
            template_id=values.get("TemplateId"),
        )

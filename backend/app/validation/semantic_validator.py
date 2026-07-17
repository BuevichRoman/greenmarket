from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawWorkbook
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET

_COL_SELLER_NAME = 1
_COL_PRODUCT_GROUP = 2
_COL_PRODUCT = 3
_COL_PRICE = 4
_COL_UNIT = 5
_COL_STOCK = 6

_OTHER_PRODUCT_PLACEHOLDER = "Прочее"


def _cell(row: list[object], index: int) -> object:
    return row[index] if index < len(row) else None


def _row_is_empty(row: list[object]) -> bool:
    return all(cell is None or cell == "" for cell in row)


class SemanticValidator:
    """Проверяет значения строк листа «Каталог»: обязательные поля не пусты,
    цена/остаток — неотрицательные числа, товарная группа/позиция существуют
    в справочниках. Не проверяет структуру (StructureValidator) и не
    проверяет бизнес-правила вроде дублей SellerProductId (BusinessValidator).
    """

    def __init__(self, product_group_repository: ProductGroupRepository, product_repository: ProductRepository):
        self.product_group_repository = product_group_repository
        self.product_repository = product_repository

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        if catalog is None or len(catalog.rows) < 2:
            return ValidationResult(errors=[])

        errors: list[ValidationError] = []
        for row_number, row in enumerate(catalog.rows[1:], start=2):
            # Google Sheets API отдаёт отформатированные, но незаполненные строки
            # шаблона (dropdown/border без данных) как строки из пустых значений —
            # такая строка не является товаром продавца.
            if _row_is_empty(row):
                continue
            errors += self._validate_row(catalog.name, row_number, row)
        return ValidationResult(errors=errors)

    def _validate_row(self, sheet_name: str, row_number: int, row: list[object]) -> list[ValidationError]:
        errors: list[ValidationError] = []

        seller_name = _cell(row, _COL_SELLER_NAME)
        if not seller_name:
            errors.append(self._required_field_empty(sheet_name, row_number, "Наименование продавца"))

        group_name = _cell(row, _COL_PRODUCT_GROUP)
        group = None
        if not group_name:
            errors.append(self._required_field_empty(sheet_name, row_number, "Товарная группа GreenMarket"))
        else:
            group = self.product_group_repository.find_by_name(group_name)
            if group is None:
                errors.append(
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Товарная группа GreenMarket",
                        message=f"Товарная группа '{group_name}' не найдена",
                    )
                )

        product_name = _cell(row, _COL_PRODUCT)
        if product_name and product_name != _OTHER_PRODUCT_PLACEHOLDER and group is not None:
            # UNIQUE(name) на Product сознательно не используется — идентификация
            # выполняется комбинацией ProductGroup + Product (см.
            # database/migrations/002_create_products.sql), поэтому товар ищем
            # именно в пределах уже найденной группы, а не по имени глобально.
            products_in_group = {product.name for product in self.product_repository.list_by_group(group.id)}
            if product_name not in products_in_group:
                errors.append(
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Товарная позиция GreenMarket",
                        message=f"Товарная позиция '{product_name}' не найдена в группе '{group_name}'",
                    )
                )

        errors += self._validate_non_negative_number(sheet_name, row_number, "Цена", _cell(row, _COL_PRICE))

        if not _cell(row, _COL_UNIT):
            errors.append(self._required_field_empty(sheet_name, row_number, "Единица продажи"))

        errors += self._validate_non_negative_number(sheet_name, row_number, "Остаток", _cell(row, _COL_STOCK))

        return errors

    def _validate_non_negative_number(self, sheet_name: str, row_number: int, column: str, value: object) -> list[ValidationError]:
        if value is None or value == "":
            return [self._required_field_empty(sheet_name, row_number, column)]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [ValidationError(sheet=sheet_name, row=row_number, column=column, message=f"'{value}' не является числом")]
        if value < 0:
            return [ValidationError(sheet=sheet_name, row=row_number, column=column, message=f"Значение {value} не может быть отрицательным")]
        return []

    def _required_field_empty(self, sheet_name: str, row_number: int, column: str) -> ValidationError:
        return ValidationError(sheet=sheet_name, row=row_number, column=column, message="Обязательное поле пусто")

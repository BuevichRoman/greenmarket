from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.cell_values import parse_supply_date
from app.parsing.raw_workbook import RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET

_COL_SELLER_NAME = 1
_COL_PRODUCT_GROUP = 2
_COL_PRODUCT = 3
_COL_PRICE = 4
_COL_UNIT = 5
_COL_STOCK = 6
_COL_PHOTOS = 9
_COL_ORIGIN_COUNTRY = 10
_COL_SUPPLY_DATE = 11

_OTHER_PRODUCT_PLACEHOLDER = "Прочее"

# Ширина SellerProduct.origin_country (миграция 016). На проде sql_mode пуст —
# слишком длинная строка не упала бы, а молча обрезалась, поэтому длину
# проверяет валидатор, а не база.
_MAX_ORIGIN_COUNTRY_LENGTH = 100


def _cell(row: list[object], index: int) -> object:
    return row[index] if index < len(row) else None


def _row_is_empty(row: list[object]) -> bool:
    return all(cell is None or cell == "" for cell in row)


class SemanticValidator:
    """Проверяет значения строк листа «Каталог»: обязательные поля не пусты,
    цена/остаток — неотрицательные числа, товарная группа/позиция существуют
    в справочниках, идентификаторы фото («Фото») — целые числа, существующие
    в Photo. Не проверяет структуру (StructureValidator) и не проверяет
    бизнес-правила вроде дублей SellerProductId (BusinessValidator).
    """

    def __init__(
        self,
        product_group_repository: ProductGroupRepository,
        product_repository: ProductRepository,
        photo_gateway: PhotoGateway,
    ):
        self.product_group_repository = product_group_repository
        self.product_repository = product_repository
        self.photo_gateway = photo_gateway

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
            errors.append(self._required_field_empty(sheet_name, row_number, "Название товара"))

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

        errors += self._validate_photos(sheet_name, row_number, _cell(row, _COL_PHOTOS))

        errors += self._validate_origin_country(sheet_name, row_number, _cell(row, _COL_ORIGIN_COUNTRY))
        errors += self._validate_supply_date(sheet_name, row_number, _cell(row, _COL_SUPPLY_DATE))

        return errors

    def _validate_origin_country(self, sheet_name: str, row_number: int, value: object) -> list[ValidationError]:
        # Колонка необязательная: пусто и отсутствие колонки (книга шаблона 2.1)
        # одинаково означают «продавец страну не указал».
        if value is None or str(value).strip() == "":
            return []
        if len(str(value).strip()) > _MAX_ORIGIN_COUNTRY_LENGTH:
            return [
                ValidationError(
                    sheet=sheet_name,
                    row=row_number,
                    column="Страна происхождения",
                    message=f"Длина не должна превышать {_MAX_ORIGIN_COUNTRY_LENGTH} символов",
                )
            ]
        return []

    def _validate_supply_date(self, sheet_name: str, row_number: int, value: object) -> list[ValidationError]:
        """Проверяется только разбираемость значения.

        Дата в будущем — не ошибка (решение Валентина 10.08.2026): будущая дата
        означает планируемую поставку, прошедшая — состоявшийся завоз. Для
        хранения это одно и то же поле, различает их тот, кто показывает
        товар покупателю, сравнивая дату с текущей.
        """
        try:
            parse_supply_date(value)
        except ValueError:
            return [
                ValidationError(
                    sheet=sheet_name,
                    row=row_number,
                    column="Дата поставки",
                    message=f"'{value}' не является датой (ожидается формат ДД.ММ.ГГГГ)",
                )
            ]
        return []

    def _validate_photos(self, sheet_name: str, row_number: int, value: object) -> list[ValidationError]:
        # Пустое фото — не ошибка: строка сохраняется, но покупателю не показывается
        # (PublicationService снимает её с публикации и возвращает в списке скрытых).
        # Заполненное, но битое значение — по-прежнему ошибка: иначе мусор в ячейке
        # молча приводил бы к тому же результату, что и осознанно пустая ячейка.
        if not value:
            return []

        parts = [part.strip() for part in str(value).split(";") if part.strip()]
        if not parts:
            return []

        photo_ids: list[int] = []
        for part in parts:
            try:
                photo_ids.append(int(part))
            except ValueError:
                return [
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Фото",
                        message=f"'{value}' содержит нечисловой идентификатор фото",
                    )
                ]

        if len(photo_ids) != len(set(photo_ids)):
            return [
                ValidationError(
                    sheet=sheet_name,
                    row=row_number,
                    column="Фото",
                    message=f"'{value}' содержит повторяющиеся идентификаторы фото",
                )
            ]

        if not self.photo_gateway.exists_all(photo_ids):
            return [
                ValidationError(
                    sheet=sheet_name,
                    row=row_number,
                    column="Фото",
                    message=f"Один или несколько идентификаторов фото не существуют: {value}",
                )
            ]
        return []

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

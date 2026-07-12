from dataclasses import dataclass

from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.errors import ValidationError, ValidationResult


@dataclass(frozen=True)
class _Column:
    name: str
    required: bool


CATALOG_SHEET = "Каталог"
PRODUCT_GROUPS_SHEET = "Товарные группы"
PRODUCTS_SHEET = "Товарные позиции"
INSTRUCTION_SHEET = "Инструкция"
SYSTEM_SHEET = "_System"

REQUIRED_SHEETS = [CATALOG_SHEET, PRODUCT_GROUPS_SHEET, PRODUCTS_SHEET, INSTRUCTION_SHEET, SYSTEM_SHEET]

# Excel Template v1.0 — согласовано с коллегой (kwork/timeline.md, п.38).
# Порядок и точные заголовки колонок фиксированы; изменение — это смена
# DocumentVersion/TemplateVersion, а не правка Parser/Validator.
CATALOG_COLUMNS = [
    _Column("SellerProductId", required=False),
    _Column("Наименование продавца", required=True),
    _Column("Товарная группа GreenMarket", required=True),
    _Column("Товарная позиция GreenMarket", required=False),
    _Column("Цена", required=True),
    _Column("Единица продажи", required=True),
    _Column("Остаток", required=True),
    _Column("Описание", required=False),
    _Column("Дополнительные характеристики", required=False),
]

PRODUCT_GROUPS_COLUMNS = [
    _Column("ProductGroupId", required=True),
    _Column("ParentProductGroupId", required=True),
    _Column("Наименование", required=True),
]

PRODUCTS_COLUMNS = [
    _Column("ProductId", required=True),
    _Column("ProductGroupId", required=True),
    _Column("Наименование", required=True),
]

SYSTEM_FIELDS = ["TemplateVersion", "TemplateId"]
SUPPORTED_TEMPLATE_VERSIONS = {"1.0"}


class StructureValidator:
    """Проверяет форму RawWorkbook против контракта Excel Template v1.0:
    обязательные листы, точные заголовки и порядок колонок, наличие
    обязательных колонок, служебные поля _System, поддерживаемую версию
    шаблона. Не проверяет значения ячеек — это SemanticValidator.
    """

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        errors: list[ValidationError] = []
        sheets_by_name = {sheet.name: sheet for sheet in workbook.sheets}

        for sheet_name in REQUIRED_SHEETS:
            if sheet_name not in sheets_by_name:
                errors.append(ValidationError(sheet=sheet_name, message=f"Отсутствует обязательный лист '{sheet_name}'"))

        if CATALOG_SHEET in sheets_by_name:
            errors += self._validate_columns(sheets_by_name[CATALOG_SHEET], CATALOG_COLUMNS)
        if PRODUCT_GROUPS_SHEET in sheets_by_name:
            errors += self._validate_columns(sheets_by_name[PRODUCT_GROUPS_SHEET], PRODUCT_GROUPS_COLUMNS)
        if PRODUCTS_SHEET in sheets_by_name:
            errors += self._validate_columns(sheets_by_name[PRODUCTS_SHEET], PRODUCTS_COLUMNS)
        if SYSTEM_SHEET in sheets_by_name:
            errors += self._validate_system_sheet(sheets_by_name[SYSTEM_SHEET])

        return ValidationResult(errors=errors)

    def _validate_columns(self, sheet: RawSheet, columns: list[_Column]) -> list[ValidationError]:
        errors: list[ValidationError] = []
        header = sheet.rows[0] if sheet.rows else []

        for index, column in enumerate(columns):
            actual = header[index] if index < len(header) else None
            if actual == column.name:
                continue
            if actual is None:
                kind = "обязательная" if column.required else "необязательная"
                errors.append(
                    ValidationError(
                        sheet=sheet.name,
                        column=column.name,
                        message=f"Отсутствует {kind} колонка '{column.name}' (позиция {index + 1})",
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        sheet=sheet.name,
                        column=column.name,
                        message=f"Колонка {index + 1}: ожидался заголовок '{column.name}', получено '{actual}'",
                    )
                )
        return errors

    def _validate_system_sheet(self, sheet: RawSheet) -> list[ValidationError]:
        errors: list[ValidationError] = []
        values = {row[0]: (row[1] if len(row) > 1 else None) for row in sheet.rows if row and row[0] in SYSTEM_FIELDS}

        for field_name in SYSTEM_FIELDS:
            value = values.get(field_name)
            if field_name not in values:
                errors.append(ValidationError(sheet=sheet.name, message=f"Отсутствует служебное поле '{field_name}'"))
            elif value is None or value == "":
                # Сервер не должен доверять служебным данным файла без проверки
                # (Catalog_Template.md, "Защита служебных данных") — пустое
                # значение служебного поля так же невалидно, как отсутствующее,
                # а не молчаливо пропускается дальше.
                errors.append(ValidationError(sheet=sheet.name, message=f"Пустое значение служебного поля '{field_name}'"))

        version = values.get("TemplateVersion")
        if version is not None and version not in SUPPORTED_TEMPLATE_VERSIONS:
            errors.append(
                ValidationError(
                    sheet=sheet.name,
                    message=f"Неподдерживаемая версия шаблона '{version}' (поддерживается: {sorted(SUPPORTED_TEMPLATE_VERSIONS)})",
                )
            )
        return errors

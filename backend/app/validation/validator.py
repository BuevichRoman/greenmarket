from app.parsing.raw_workbook import RawWorkbook
from app.validation.business_validator import BusinessValidator
from app.validation.errors import ValidationResult
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator


class Validator:
    """Оркестрирует StructureValidator → SemanticValidator + BusinessValidator.

    Если структура каталога нарушена, построчные проверки не запускаются —
    ошибки про несуществующие колонки были бы шумом поверх уже понятной
    структурной ошибки (см. Publication_Workflow.md: Structure Validation
    предшествует Business Validation, а не выполняется параллельно с ней).
    Semantic и Business при валидной структуре выполняются оба — их ошибки
    собираются в один отчёт, не fail-fast (Publication_Service.md).
    """

    def __init__(
        self,
        structure_validator: StructureValidator,
        semantic_validator: SemanticValidator,
        business_validator: BusinessValidator,
    ):
        self.structure_validator = structure_validator
        self.semantic_validator = semantic_validator
        self.business_validator = business_validator

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        structure_result = self.structure_validator.validate(workbook)
        if not structure_result.is_valid:
            return structure_result

        errors = []
        errors += self.semantic_validator.validate(workbook).errors
        errors += self.business_validator.validate(workbook).errors
        return ValidationResult(errors=errors)

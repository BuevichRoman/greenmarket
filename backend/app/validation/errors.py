from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationError:
    sheet: str
    message: str
    row: int | None = None
    column: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

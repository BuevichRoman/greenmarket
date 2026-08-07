"""Ошибки профиля продавца — по образцу app/publication/errors.py и
app/admin/seller_onboarding.py: наружу выходят только именованные свои
исключения, которые эндпоинт ловит поимённо.

Наследуются от `Exception`, а не от `LookupError`/`ValueError`, намеренно.
Раньше сервис бросал голый `LookupError` («продавец не найден») и голый
`ValueError` («значение длиннее максимума»), а из гейтвея сквозь него летели
`UnknownPropError`/`UnsupportedPropTypeError` — тоже `LookupError`. Четыре
разных ответа (400, 404, 500) оказывались неразличимы, а `KeyError` и
`IndexError` наследуют `LookupError` сами, поэтому обычный баг в коде доехал
бы до покупателя как «продавец не найден».

Ошибки окружения (свойство не заведено в `users_prop`, неподдерживаемый тип
значения) сюда намеренно не заворачиваются: это не бизнес-ситуация, а
несогласованность окружения, и ей полагается падать пятисоткой с исходным
типом в логе.
"""


class ProfileError(Exception):
    """Базовая ошибка профиля."""


class ProfileValidationError(ProfileError):
    """Клиент прислал то, чего принять нельзя, — эндпоинту это 422.

    Промежуточный класс существует ради эндпоинтов: ответ у неизвестного поля
    и у слишком длинного значения один и тот же, а различать их в каждом из
    четырёх обработчиков пришлось бы поимённо.
    """


class UnknownProfileFieldError(ProfileValidationError):
    def __init__(self, field_names: list[str]):
        super().__init__(f"Неизвестные поля профиля: {', '.join(field_names)}")
        self.field_names = field_names


class ProfileValueTooLongError(ProfileValidationError):
    def __init__(self, field_name: str, max_length: int):
        super().__init__(f"Поле «{field_name}» длиннее допустимых {max_length} символов")
        self.field_name = field_name
        self.max_length = max_length


class SellerNotFoundError(ProfileError):
    """Продавца с таким id нет — эндпоинту это 404."""

    def __init__(self, seller_id: int):
        super().__init__(f"Продавец {seller_id} не найден")
        self.seller_id = seller_id

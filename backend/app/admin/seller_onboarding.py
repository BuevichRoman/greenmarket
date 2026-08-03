"""Подключение продавца к платформе — одна админская бизнес-операция.

Раньше это была последовательность из трёх ручных шагов (INSERT в Seller через
phpMyAdmin, запуск scripts/issue_activation_code.py по SSH, копирование кода),
то есть администратор обязан был знать внутреннее устройство БД и иметь доступ
к серверу. Операция описывается в терминах бизнеса — «подключить пользователя
как продавца», — а не в терминах таблиц.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.platform.seller_gateway import SellerGateway
from app.publication.seller_activation import issue_activation_code


class OnboardingError(Exception):
    """Базовая ошибка онбординга — наружу выходят только свои исключения."""


class UserNotFoundError(OnboardingError):
    def __init__(self, user_id: int):
        super().__init__(f"Пользователь платформы {user_id} не найден")
        self.user_id = user_id


class SellerAlreadyExistsError(OnboardingError):
    def __init__(self, seller_id: int):
        super().__init__(f"Продавец для этого пользователя уже существует (seller_id={seller_id})")
        self.seller_id = seller_id


@dataclass(frozen=True)
class OnboardingResult:
    seller_id: int
    activation_code: str


def onboard_seller(user_id: int, *, session: Session) -> OnboardingResult:
    """Создаёт учётную запись продавца и сразу выдаёт код активации.

    Рабочий токен здесь не выдаётся: продавец получает его сам, обменяв код
    через POST /api/v1/seller/activate. Онбординг подключает продавца к
    платформе, а не открывает его каталог покупателям — видимость товаров
    определяется отдельными правилами (см. Publication_Model.md).

    Не коммитит — за commit() отвечает вызывающий.
    """
    gateway = SellerGateway(session)
    if not gateway.user_exists(user_id):
        raise UserNotFoundError(user_id)

    existing_seller_id = gateway.find_seller_id_by_user(user_id)
    if existing_seller_id is not None:
        raise SellerAlreadyExistsError(existing_seller_id)

    seller_id = gateway.create(user_id)
    activation_code = issue_activation_code(seller_id, session=session)
    if activation_code is None:  # pragma: no cover - Seller только что создан
        raise OnboardingError(f"Не удалось выдать код активации продавцу {seller_id}")

    return OnboardingResult(seller_id=seller_id, activation_code=activation_code)

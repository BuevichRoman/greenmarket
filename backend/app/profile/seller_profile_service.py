"""Чтение и изменение профиля продавца.

Один сервис на трёх потребителей (книга продавца, Admin API, Catalog API) —
иначе правило «что считать изменением» и запись журнала пришлось бы повторять в
каждом.

Транзакцией сервис не управляет: `commit()` делает вызывающий эндпоинт, как и
во всём остальном коде (см. app/publication/publication_service.py).
"""

from sqlalchemy.orm import Session

from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.platform.seller_gateway import SellerGateway
from app.platform.user_prop_gateway import UserPropGateway
from app.profile.fields import PROFILE_FIELDS, ProfileField, field_by_name


class UnknownProfileFieldError(LookupError):
    """В запросе поле, которого нет в профиле."""


class SellerProfileService:
    def __init__(self, session: Session):
        self.session = session
        self.props = UserPropGateway(session)
        self.sellers = SellerGateway(session)
        self.journal = SellerProfileChangeRepository(session)

    def _user_id(self, seller_id: int) -> int | None:
        row = self.sellers.find_list_row(seller_id)
        return None if row is None else row.user_id

    def read(self, seller_id: int) -> dict[str, str | None]:
        """Профиль продавца. Незаполненные поля — `None`, а не отсутствующие
        ключи: потребителю (форма, карточка) удобнее одинаковый набор ключей."""
        user_id = self._user_id(seller_id)
        if user_id is None:
            return {field.name: None for field in PROFILE_FIELDS}
        stored = self.props.read(user_id, [field.prop_var for field in PROFILE_FIELDS])
        return {field.name: stored.get(field.prop_var) for field in PROFILE_FIELDS}

    def suggested_phone(self, seller_id: int) -> str | None:
        """Подсказка для незаполненного телефона — учётный номер платформы.

        Отдаётся отдельным полем ответа, а не подставляется в `phone`: пока
        продавец не сохранил номер сам, витринного телефона у него нет, и
        покупателю показывать учётный номер из такси мы не имеем права.
        Договорённость с архитектором 06.08.2026: предзаполняем, продавец
        подтверждает или переопределяет.
        """
        if self.read(seller_id)["phone"] is not None:
            return None
        user_id = self._user_id(seller_id)
        return None if user_id is None else self.props.platform_phone(user_id)

    @staticmethod
    def _normalize(values: dict[str, str | None]) -> dict[ProfileField, str | None]:
        """Приводит присланные значения к тому, что ляжет в хранилище, и
        проверяет длину — всё до единой записи, чтобы неудачная валидация не
        оставила половину формы сохранённой.

        Длину проверяем здесь, а не полагаемся на БД: у varchar-полей MySQL
        ответил бы DataError мимо конвенции `{"error": {...}}`, а у
        `short_description` не ответил бы вовсе — колонка держит 65535
        символов, ограничение 2000 наше продуктовое.
        """
        unknown = {name for name in values if field_by_name(name) is None}
        if unknown:
            raise UnknownProfileFieldError(
                f"Неизвестные поля профиля: {', '.join(sorted(unknown))}"
            )

        normalized: dict[ProfileField, str | None] = {}
        for name, raw in values.items():
            field = field_by_name(name)
            assert field is not None  # проверено выше
            new_value = (raw or "").strip() or None
            if new_value is not None and len(new_value) > field.max_length:
                raise ValueError(
                    f"Поле «{name}» длиннее допустимых {field.max_length} символов"
                )
            normalized[field] = new_value
        return normalized

    def apply(
        self,
        seller_id: int,
        values: dict[str, str | None],
        *,
        author_user_id: int,
        author_role: str,
    ) -> list[str]:
        """Применяет изменения и возвращает имена реально изменившихся полей.

        Поля, которых нет в `values`, не трогаются — форма может присылать
        только то, что редактировала. Пустая строка и `None` означают очистку.
        """
        normalized = self._normalize(values)

        user_id = self._user_id(seller_id)
        if user_id is None:
            raise LookupError(f"Продавец {seller_id} не найден")

        current = self.read(seller_id)
        changed: list[str] = []

        for field, new_value in normalized.items():
            old_value = current[field.name]
            if new_value == old_value:
                continue

            if new_value is None:
                self.props.clear(user_id, field.prop_var)
            else:
                self.props.write(user_id, field.prop_var, new_value)

            self.journal.record(
                seller_id=seller_id,
                field=field.name,
                old_value=old_value,
                new_value=new_value,
                author_user_id=author_user_id,
                author_role=author_role,
            )
            changed.append(field.name)

        return changed

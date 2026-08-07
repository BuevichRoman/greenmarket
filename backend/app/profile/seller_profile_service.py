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
from app.profile.errors import (
    ProfileValueTooLongError,
    SellerNotFoundError,
    UnknownProfileFieldError,
)
from app.profile.fields import PROFILE_FIELDS, ProfileField, field_by_name


class SellerProfileService:
    def __init__(self, session: Session):
        self.session = session
        self.props = UserPropGateway(session)
        self.sellers = SellerGateway(session)
        self.journal = SellerProfileChangeRepository(session)
        # user_id продавца за время жизни сервиса не меняется, а спрашивают его
        # много раз за запрос: read() на каждый вызов, suggested_phone() поверх
        # read() ещё раз, apply() до и после. Кэш ключом по seller_id, а не
        # одним полем: один экземпляр сервиса обслуживает и несколько продавцов
        # (например, лента админа).
        self._user_ids: dict[int, int | None] = {}

    def _user_id(self, seller_id: int) -> int | None:
        if seller_id not in self._user_ids:
            row = self.sellers.find_list_row(seller_id)
            self._user_ids[seller_id] = None if row is None else row.user_id
        return self._user_ids[seller_id]

    def read(self, seller_id: int) -> dict[str, str | None]:
        """Профиль продавца. Незаполненные поля — `None`, а не отсутствующие
        ключи: потребителю (форма, карточка) удобнее одинаковый набор ключей.

        У несуществующего продавца профиль тоже читается — весь из `None`, без
        ошибки. Отличить его от продавца с пустым профилем здесь нельзя и не
        нужно: 404 отдаёт эндпоинт, который проверяет существование продавца
        сам, а `apply()` для этого бросает SellerNotFoundError.
        """
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
    def _validated_values(values: dict[str, str | None]) -> dict[ProfileField, str | None]:
        """Защитный шлюз перед записью: отсеивает неизвестные поля, приводит
        значения к тому, что ляжет в хранилище (strip, пустое → `None`), и
        проверяет длину.

        Всё это до единой записи: иначе неудачная валидация оставила бы часть
        формы сохранённой, а вызывающий получил бы ошибку и не узнал, что
        что-то всё-таки записалось.

        Длину проверяем здесь, а не полагаемся на БД: у varchar-полей ответ
        зависит от sql_mode (на проде он пустой — значение молча обрежется), а
        у `short_description` БД не возразит в любом случае — колонка
        `users_prop_items_text.value` держит 65535 символов, ограничение 2000
        наше продуктовое.
        """
        resolved = [(name, field_by_name(name), raw) for name, raw in values.items()]

        unknown = sorted(name for name, field, _ in resolved if field is None)
        if unknown:
            raise UnknownProfileFieldError(unknown)

        validated: dict[ProfileField, str | None] = {}
        for name, field, raw in resolved:
            new_value = (raw or "").strip() or None
            if new_value is not None and len(new_value) > field.max_length:
                raise ProfileValueTooLongError(name, field.max_length)
            validated[field] = new_value
        return validated

    def apply(
        self,
        seller_id: int,
        values: dict[str, str | None],
        *,
        author_user_id: int,
        author_role: str,
    ) -> list[str]:
        """Применяет изменения и возвращает имена реально изменившихся полей.

        Поля, которых нет в `values`, не трогаются — форма присылает только то,
        что редактировала (эндпоинт кормит сюда `exclude_unset`). Очистка — это
        явно присланная пустая строка или `None`, а не отсутствие ключа.

        `author_user_id` — тот, кто правит, а не владелец профиля: у админа это
        не совпадает с продавцом, и весь смысл журнала в том, чтобы эти два
        случая различать.
        """
        validated = self._validated_values(values)

        user_id = self._user_id(seller_id)
        if user_id is None:
            raise SellerNotFoundError(seller_id)

        current = self.read(seller_id)
        changed: list[str] = []

        # Обход по PROFILE_FIELDS, а не по присланному словарю: порядок ответа
        # не должен зависеть от того, в каком порядке клиент собрал JSON.
        for field in PROFILE_FIELDS:
            if field not in validated:
                continue
            new_value = validated[field]
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

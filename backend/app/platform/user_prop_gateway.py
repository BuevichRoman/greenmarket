"""Anti-Corruption Layer к платформенным данным пользователя: к механизму
расширяемых свойств (`users_prop` + `users_prop_items_varchar|text`) и к
учётному телефону `users.phone`, который читается только ради предзаполнения
профиля.

Тот же принцип, что у SellerGateway: GreenMarket не владеет этими таблицами и
не отображает их как ORM-модели. Если платформа однажды закроет прямой доступ к
БД и даст REST/gRPC, меняется только этот файл.

Свойство всегда резолвится по `var`, никогда по числовому `id_users_prop`: он
разный в боевой и локальной базе, и хардкод сломался бы молча — записал бы
значение в чужое свойство.
"""

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

# Значения платформенного `users_prop.value_type` (FK на её словарь field_type).
# Объявлены здесь, а не в продуктовом app/profile: это знание о чужой схеме, и
# ему полагается жить за ACL — вместе со всем остальным, что меняется, если
# платформа сменит способ хранения свойств. Типов в словаре больше двух,
# поддержаны ровно те, которыми пользуется GreenMarket.
VALUE_TYPE_VARCHAR = 1
VALUE_TYPE_TEXT = 2

# Имя таблицы значений подставляется в SQL форматированием, поэтому берётся
# только отсюда — из закрытого словаря, а не из аргументов вызова.
_ITEMS_TABLE = {
    VALUE_TYPE_VARCHAR: "users_prop_items_varchar",
    VALUE_TYPE_TEXT: "users_prop_items_text",
}

# Границы правдоподобия для users.phone: колонка BIGINT, заполняется формой
# такси без строгой валидации — на проде встречаются значения от одной цифры.
# Подставлять такое продавцу как готовый телефон нельзя.
_PLAUSIBLE_PHONE_LENGTH = range(10, 16)


class UnknownPropError(LookupError):
    """Свойства с таким `var` нет в `users_prop`.

    Определения свойств заводит платформа (на проде — вручную, users_prop это
    её конфигурационная таблица), поэтому их отсутствие означает
    рассинхронизацию окружения, а не пользовательскую ошибку.
    """


class UnsupportedPropTypeError(LookupError):
    """У свойства тип значения, который GreenMarket не умеет хранить.

    Соседка UnknownPropError: типов в платформенном словаре field_type больше
    двух (например, 3 — int), но своей таблицы значений под каждый у нас нет.
    Явная ошибка вместо KeyError из недр словаря таблиц — чтобы в логе было
    видно, какое свойство и какой тип, а не только «3».
    """


class UserPropGateway:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _items_table(prop_var: str, value_type: int) -> str:
        try:
            return _ITEMS_TABLE[value_type]
        except KeyError:
            raise UnsupportedPropTypeError(
                f"Свойство {prop_var}: тип значения {value_type} не поддерживается"
            ) from None

    def _resolve(self, prop_vars: list[str]) -> dict[str, tuple[int, int]]:
        """`var` → (`id_users_prop`, `value_type`) одним запросом."""
        if not prop_vars:
            return {}
        stmt = text(
            "SELECT var, id_users_prop, value_type FROM users_prop WHERE var IN :prop_vars"
        ).bindparams(bindparam("prop_vars", expanding=True))
        rows = self.session.execute(stmt, {"prop_vars": prop_vars}).all()
        resolved = {row[0]: (row[1], row[2]) for row in rows}
        missing = set(prop_vars) - resolved.keys()
        if missing:
            raise UnknownPropError(f"Свойства не заведены в users_prop: {', '.join(sorted(missing))}")
        return resolved

    def read(self, user_id: int, prop_vars: list[str]) -> dict[str, str]:
        """Значения свойств пользователя. Незаполненные в результат не попадают:
        `value` в таблицах значений объявлена NOT NULL, поэтому «пусто» — это
        отсутствие строки."""
        resolved = self._resolve(prop_vars)
        by_table: dict[str, list[int]] = {}
        prop_var_by_id: dict[int, str] = {}
        for prop_var, (prop_id, value_type) in resolved.items():
            by_table.setdefault(self._items_table(prop_var, value_type), []).append(prop_id)
            prop_var_by_id[prop_id] = prop_var

        values: dict[str, str] = {}
        for table, prop_ids in by_table.items():
            stmt = text(
                f"SELECT id_users_prop, value FROM {table} "
                "WHERE id_user = :user_id AND id_users_prop IN :prop_ids"
            ).bindparams(bindparam("prop_ids", expanding=True))
            rows = self.session.execute(stmt, {"user_id": user_id, "prop_ids": prop_ids}).all()
            for prop_id, value in rows:
                values[prop_var_by_id[prop_id]] = value
        return values

    def write(self, user_id: int, prop_var: str, value: str) -> None:
        prop_id, value_type = self._resolve([prop_var])[prop_var]
        table = self._items_table(prop_var, value_type)
        self.session.execute(
            text(
                f"INSERT INTO {table} (id_users_prop, id_user, value) "
                "VALUES (:prop_id, :user_id, :value) "
                "ON DUPLICATE KEY UPDATE value = :value"
            ),
            {"prop_id": prop_id, "user_id": user_id, "value": value},
        )

    def clear(self, user_id: int, prop_var: str) -> None:
        """Очистка — DELETE, а не запись пустой строки: `value` NOT NULL, и
        пустая строка в карточке покупателя выглядела бы как заполненное поле."""
        prop_id, value_type = self._resolve([prop_var])[prop_var]
        table = self._items_table(prop_var, value_type)
        self.session.execute(
            text(f"DELETE FROM {table} WHERE id_users_prop = :prop_id AND id_user = :user_id"),
            {"prop_id": prop_id, "user_id": user_id},
        )

    def platform_phone(self, user_id: int) -> str | None:
        """Учётный телефон платформы — только для предзаполнения профиля.

        GreenMarket в `users.phone` не пишет никогда: это учётное поле с флагом
        верификации, по нему в такси логинятся (договорённость с Валентином от
        06.08.2026). Правдоподобие проверяется, потому что колонка BIGINT без
        валидации на стороне платформы.
        """
        row = self.session.execute(
            text("SELECT phone FROM users WHERE id_user = :user_id"), {"user_id": user_id}
        ).first()
        if row is None or row[0] is None:
            return None
        phone = str(row[0])
        return phone if len(phone) in _PLAUSIBLE_PHONE_LENGTH else None

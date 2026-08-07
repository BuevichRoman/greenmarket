"""Состав профиля продавца — единственный источник правды.

К профилю обращаются три разных потребителя: книга продавца через Seller API и
администратор через Admin API его читают и правят, покупатель через Catalog API
только читает. Если набор полей описать в каждом из них отдельно, он разъедется
при первом же изменении, а изменения тут будут: Stage 2 добавляет фото, логотип,
соцсети и справочник Market (Seller_Profile.md, §4 и §11).

Значения лежат в платформенном механизме свойств. `prop_var` — ключ свойства в
`users_prop.var`; числовой `id_users_prop` в коде не используется никогда, он
разный в разных базах.
"""

from dataclasses import dataclass

from app.platform.user_prop_gateway import VALUE_TYPE_TEXT, VALUE_TYPE_VARCHAR


@dataclass(frozen=True)
class ProfileField:
    name: str
    prop_var: str
    value_type: int
    max_length: int


# Здесь только те поля профиля, которыми владеет GreenMarket. `name` и `status`
# (Seller_Profile.md, §5) — тоже поля профиля, но хранятся не в свойствах:
# `name` это users.name платформы, `status` это Seller.is_active.
#
# max_length у varchar-полей равен ширине users_prop_items_varchar.value (255).
# short_description лежит в users_prop_items_text; ограничение 2000 — наше
# продуктовое, а не схемное: краткое описание в карточке продавца
# (Seller_Profile.md, §9), не статья.
#
# Все поля Stage 1 публичны — Seller_Profile.md, §7: покупателю показываются
# все поля профиля, кроме системных. Поэтому карточка покупателя собирается
# как `{seller_id, name, **profile}` (app/application/catalog_use_case.py,
# get_seller_card), и тесты сверяют её состав прямо с этим кортежем.
#
# Отсюда следствие для Stage 2: добавленное сюда поле по умолчанию уезжает на
# анонимный эндпоинт. Если новое поле покупателю показывать нельзя, это
# решение принимается здесь и в get_seller_card — фильтром на стороне карточки
# (у платформенного свойства для этого есть колонка `users_prop.visibility`), а
# не дописыванием поля в SellerCardResponse ради зелёного теста.
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    ProfileField("row", "gm_seller_row", VALUE_TYPE_VARCHAR, 255),
    ProfileField("place", "gm_seller_place", VALUE_TYPE_VARCHAR, 255),
    ProfileField("working_hours", "gm_seller_working_hours", VALUE_TYPE_VARCHAR, 255),
    ProfileField("short_description", "gm_seller_short_description", VALUE_TYPE_TEXT, 2000),
    ProfileField("phone", "gm_seller_phone", VALUE_TYPE_VARCHAR, 255),
    ProfileField("whatsapp", "gm_seller_whatsapp", VALUE_TYPE_VARCHAR, 255),
)

_BY_NAME = {field.name: field for field in PROFILE_FIELDS}


def field_by_name(name: str) -> ProfileField | None:
    return _BY_NAME.get(name)

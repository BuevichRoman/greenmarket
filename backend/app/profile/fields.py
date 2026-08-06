"""Состав профиля продавца — единственный источник правды.

Профиль читают и пишут три разных потребителя (книга продавца через Seller API,
администратор через Admin API, покупатель через Catalog API). Если набор полей
описать в каждом из них отдельно, он разъедется при первом же изменении, а
изменения тут будут: Stage 2 добавляет фото, логотип, соцсети и справочник
Market (Seller_Profile.md, §4 и §11).

Значения лежат в платформенном механизме свойств. `prop_var` — ключ свойства в
`users_prop.var`; числовой `id_users_prop` в коде не используется никогда, он
разный в разных базах.
"""

from dataclasses import dataclass

VALUE_TYPE_VARCHAR = 1
VALUE_TYPE_TEXT = 2


@dataclass(frozen=True)
class ProfileField:
    name: str
    prop_var: str
    value_type: int
    max_length: int


# max_length у varchar-полей равен ширине users_prop_items_varchar.value (255).
# short_description лежит в users_prop_items_text; ограничение 2000 — наше
# продуктовое, а не схемное: краткое описание в карточке продавца
# (Seller_Profile.md, §9), не статья.
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    ProfileField("row", "gm_seller_row", VALUE_TYPE_VARCHAR, 255),
    ProfileField("place", "gm_seller_place", VALUE_TYPE_VARCHAR, 255),
    ProfileField("working_hours", "gm_seller_working_hours", VALUE_TYPE_VARCHAR, 255),
    ProfileField("short_description", "gm_seller_short_description", VALUE_TYPE_TEXT, 2000),
    ProfileField("phone", "gm_seller_phone", VALUE_TYPE_VARCHAR, 255),
    ProfileField("whatsapp", "gm_seller_whatsapp", VALUE_TYPE_VARCHAR, 255),
)

# Пока редактируются все поля профиля, но список отделён намеренно: name и
# status тоже поля профиля (Seller_Profile.md, §5), просто владеет ими не
# GreenMarket — name это users.name платформы, status это Seller.is_active.
EDITABLE_FIELDS: tuple[ProfileField, ...] = PROFILE_FIELDS

_BY_NAME = {field.name: field for field in PROFILE_FIELDS}


def field_by_name(name: str) -> ProfileField | None:
    return _BY_NAME.get(name)

from app.platform.user_prop_gateway import VALUE_TYPE_TEXT
from app.profile.fields import PROFILE_FIELDS, field_by_name


def test_profile_fields_cover_stage1_profile():
    assert [field.name for field in PROFILE_FIELDS] == [
        "row",
        "place",
        "working_hours",
        "short_description",
        "phone",
        "whatsapp",
        # Добавлено 10.08.2026 вместе со справочником рынков (миграция 017):
        # рынок — часть профиля продавца, хотя его название, адрес и координаты
        # принадлежат самому рынку (Seller_Profile.md, §3).
        "market_id",
    ]


def test_every_field_maps_to_greenmarket_prop():
    for field in PROFILE_FIELDS:
        assert field.prop_var.startswith("gm_seller_")


def test_short_description_is_the_only_text_field():
    assert [field.name for field in PROFILE_FIELDS if field.value_type == VALUE_TYPE_TEXT] == [
        "short_description"
    ]


def test_field_by_name_rejects_unknown_field():
    assert field_by_name("row") is not None
    assert field_by_name("id_role") is None

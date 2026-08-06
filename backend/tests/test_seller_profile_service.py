from app.profile.fields import EDITABLE_FIELDS, PROFILE_FIELDS, field_by_name


def test_editable_fields_cover_stage1_profile():
    assert [field.name for field in EDITABLE_FIELDS] == [
        "row",
        "place",
        "working_hours",
        "short_description",
        "phone",
        "whatsapp",
    ]


def test_every_field_maps_to_greenmarket_prop():
    for field in PROFILE_FIELDS:
        assert field.prop_var.startswith("gm_seller_")


def test_short_description_is_the_only_text_field():
    assert [field.name for field in PROFILE_FIELDS if field.value_type == 2] == ["short_description"]


def test_field_by_name_rejects_unknown_field():
    assert field_by_name("row") is not None
    assert field_by_name("id_role") is None

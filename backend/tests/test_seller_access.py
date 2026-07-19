from app.publication.seller_access import resolve_seller_access


def test_valid_token_resolves_to_seller_access():
    tokens_json = '{"tok-abc": {"seller_id": 1, "published_by": 457, "name": "Ферма Ромашково"}}'

    access = resolve_seller_access("tok-abc", tokens_json=tokens_json)

    assert access is not None
    assert access.seller_id == 1
    assert access.published_by == 457
    assert access.name == "Ферма Ромашково"


def test_unknown_token_resolves_to_none():
    tokens_json = '{"tok-abc": {"seller_id": 1, "published_by": 457, "name": "Ферма Ромашково"}}'

    access = resolve_seller_access("tok-does-not-exist", tokens_json=tokens_json)

    assert access is None


def test_empty_tokens_config_resolves_to_none():
    access = resolve_seller_access("anything", tokens_json="{}")

    assert access is None

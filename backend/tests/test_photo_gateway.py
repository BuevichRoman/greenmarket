from sqlalchemy import text

from app.platform.photo_gateway import PhotoGateway


def insert_seller_product_photo(session, *, seller_product_id: int, s3_key: str, sort_order: int) -> int:
    photo_id = session.execute(
        text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}
    ).lastrowid
    session.execute(
        text(
            "INSERT INTO SellerProductPhoto (seller_product_id, photo_id, sort_order) "
            "VALUES (:seller_product_id, :photo_id, :sort_order)"
        ),
        {"seller_product_id": seller_product_id, "photo_id": photo_id, "sort_order": sort_order},
    )
    return photo_id


def test_list_by_seller_products_returns_keys_ordered_by_sort_order(session, seller_product_id):
    insert_seller_product_photo(session, seller_product_id=seller_product_id, s3_key="b.jpg", sort_order=1)
    insert_seller_product_photo(session, seller_product_id=seller_product_id, s3_key="a.jpg", sort_order=0)

    result = PhotoGateway(session).list_by_seller_products([seller_product_id])

    assert result == {seller_product_id: ["a.jpg", "b.jpg"]}


def test_list_by_seller_products_returns_empty_dict_for_empty_input(session):
    assert PhotoGateway(session).list_by_seller_products([]) == {}


def test_list_by_seller_products_omits_seller_products_without_photos(session, seller_product_id):
    result = PhotoGateway(session).list_by_seller_products([seller_product_id])

    assert result == {}


def test_create_inserts_photo_and_returns_id(session):
    photo_id = PhotoGateway(session).create(s3_key="new.jpg", seller_id=7)

    row = session.execute(
        text("SELECT s3_key, seller_id FROM Photo WHERE id = :id"), {"id": photo_id}
    ).first()
    assert row == ("new.jpg", 7)


def test_exists_all_returns_true_when_every_id_exists(session):
    photo_id = PhotoGateway(session).create(s3_key="exists.jpg", seller_id=1)

    assert PhotoGateway(session).exists_all([photo_id]) is True


def test_exists_all_returns_false_when_any_id_is_missing(session):
    photo_id = PhotoGateway(session).create(s3_key="exists2.jpg", seller_id=1)

    assert PhotoGateway(session).exists_all([photo_id, 999_999_999]) is False


def test_exists_all_returns_true_for_empty_list(session):
    assert PhotoGateway(session).exists_all([]) is True


def test_list_by_ids_and_seller_returns_matching_photos(session):
    photo_a = PhotoGateway(session).create(s3_key="own-a.jpg", seller_id=10)
    photo_b = PhotoGateway(session).create(s3_key="own-b.jpg", seller_id=10)

    result = PhotoGateway(session).list_by_ids_and_seller([photo_a, photo_b], seller_id=10)

    assert set(result) == {(photo_a, "own-a.jpg"), (photo_b, "own-b.jpg")}


def test_list_by_ids_and_seller_omits_other_sellers_photos(session):
    own_photo = PhotoGateway(session).create(s3_key="own.jpg", seller_id=10)
    other_photo = PhotoGateway(session).create(s3_key="other.jpg", seller_id=20)

    result = PhotoGateway(session).list_by_ids_and_seller([own_photo, other_photo], seller_id=10)

    assert result == [(own_photo, "own.jpg")]


def test_list_by_ids_and_seller_omits_nonexistent_ids(session):
    own_photo = PhotoGateway(session).create(s3_key="own2.jpg", seller_id=10)

    result = PhotoGateway(session).list_by_ids_and_seller([own_photo, 999_999_999], seller_id=10)

    assert result == [(own_photo, "own2.jpg")]


def test_list_by_ids_and_seller_returns_empty_list_for_empty_input(session):
    assert PhotoGateway(session).list_by_ids_and_seller([], seller_id=10) == []

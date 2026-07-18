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

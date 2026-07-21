from sqlalchemy import text

from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository


def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid


def test_replace_for_product_creates_rows_in_order(session, seller_product_id):
    photo_a = insert_photo(session, s3_key="repo-a.jpg")
    photo_b = insert_photo(session, s3_key="repo-b.jpg")

    SellerProductPhotoRepository(session).replace_for_product(seller_product_id, [photo_a, photo_b])

    assert SellerProductPhotoRepository(session).list_photo_ids(seller_product_id) == [photo_a, photo_b]


def test_replace_for_product_removes_previous_set(session, seller_product_id):
    photo_a = insert_photo(session, s3_key="repo-c.jpg")
    photo_b = insert_photo(session, s3_key="repo-d.jpg")
    repository = SellerProductPhotoRepository(session)
    repository.replace_for_product(seller_product_id, [photo_a, photo_b])

    repository.replace_for_product(seller_product_id, [photo_b])

    assert repository.list_photo_ids(seller_product_id) == [photo_b]


def test_replace_for_product_with_empty_list_clears_all_photos(session, seller_product_id):
    photo_a = insert_photo(session, s3_key="repo-e.jpg")
    repository = SellerProductPhotoRepository(session)
    repository.replace_for_product(seller_product_id, [photo_a])

    repository.replace_for_product(seller_product_id, [])

    assert repository.list_photo_ids(seller_product_id) == []


def test_list_photo_ids_returns_empty_list_when_no_photos(session, seller_product_id):
    assert SellerProductPhotoRepository(session).list_photo_ids(seller_product_id) == []

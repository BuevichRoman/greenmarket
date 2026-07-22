import io

from app.api.v1.photos import get_photo_storage, get_seller_access_resolver
from app.main import app
from app.publication.seller_access import SellerAccess

VALID_TOKEN = "photo-test-token"


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.calls.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})


def override_seller_access(seller_id: int, published_by: int) -> None:
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name="Тестовый продавец")
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: access if token == VALID_TOKEN else None)


def override_storage():
    from app.platform.photo_storage import PhotoStorage

    fake_client = FakeS3Client()
    storage = PhotoStorage(bucket="test-bucket", client=fake_client)
    app.dependency_overrides[get_photo_storage] = lambda: storage
    return fake_client


def override_session(session):
    from app.infrastructure.database import get_session

    app.dependency_overrides[get_session] = lambda: (yield session)


def test_upload_photo_returns_201_with_photo_id(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=1, published_by=1)
    override_storage()
    client = TestClient(app)

    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("photo.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert isinstance(response.json()["photo_id"], int)


def test_upload_photo_persists_seller_id(committing_session):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    override_session(committing_session)
    override_seller_access(seller_id=42, published_by=1)
    override_storage()
    client = TestClient(app)

    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("photo.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )

    photo_id = response.json()["photo_id"]
    row = committing_session.execute(text("SELECT seller_id FROM Photo WHERE id = :id"), {"id": photo_id}).first()
    assert row == (42,)


def test_upload_photo_with_invalid_token_returns_403(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: None)
    override_storage()
    client = TestClient(app)

    response = client.post(
        "/api/v1/photos",
        data={"access_token": "not-a-real-token"},
        files={"file": ("photo.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_upload_photo_with_unsupported_content_type_returns_422(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=1, published_by=1)
    override_storage()
    client = TestClient(app)

    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_CONTENT_TYPE"


def test_upload_photo_over_size_limit_returns_413(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=1, published_by=1)
    override_storage()
    client = TestClient(app)

    oversized = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("big.jpg", io.BytesIO(oversized), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_photo_at_exact_size_limit_succeeds(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=1, published_by=1)
    override_storage()
    client = TestClient(app)

    exact = b"x" * (10 * 1024 * 1024)
    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("exact.jpg", io.BytesIO(exact), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert isinstance(response.json()["photo_id"], int)


def test_upload_photo_storage_failure_returns_500(committing_session):
    from fastapi.testclient import TestClient

    from app.platform.photo_storage import PhotoStorage

    class FailingPhotoStorage(PhotoStorage):
        def upload(self, file_bytes, content_type):
            raise RuntimeError("S3 недоступен")

    override_session(committing_session)
    override_seller_access(seller_id=1, published_by=1)
    app.dependency_overrides[get_photo_storage] = lambda: FailingPhotoStorage(bucket="test-bucket", client=FakeS3Client())
    client = TestClient(app)

    response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("photo.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "PHOTO_STORAGE_ERROR"


def test_list_photos_returns_urls_for_own_photos(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=5, published_by=1)
    override_storage()
    client = TestClient(app)

    upload_response = client.post(
        "/api/v1/photos",
        data={"access_token": VALID_TOKEN},
        files={"file": ("photo.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )
    photo_id = upload_response.json()["photo_id"]

    response = client.get(f"/api/v1/photos?ids={photo_id}&access_token={VALID_TOKEN}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    photos = response.json()["photos"]
    assert len(photos) == 1
    assert photos[0]["photo_id"] == photo_id
    assert photos[0]["url"].endswith(".jpg")


def test_list_photos_omits_other_sellers_photos(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_storage()

    seller_a = SellerAccess(seller_id=5, published_by=1, name="Продавец А")
    seller_b = SellerAccess(seller_id=6, published_by=1, name="Продавец Б")
    tokens = {"token-a": seller_a, "token-b": seller_b}
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: tokens.get(token))
    client = TestClient(app)

    other_photo = client.post(
        "/api/v1/photos",
        data={"access_token": "token-b"},
        files={"file": ("b.jpg", io.BytesIO(b"b"), "image/jpeg")},
    ).json()["photo_id"]

    response = client.get(f"/api/v1/photos?ids={other_photo}&access_token=token-a")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["photos"] == []


def test_list_photos_with_invalid_token_returns_403(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: None)
    client = TestClient(app)

    response = client.get("/api/v1/photos?ids=1&access_token=not-a-real-token")

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_list_photos_with_non_numeric_ids_returns_422(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=5, published_by=1)
    client = TestClient(app)

    response = client.get(f"/api/v1/photos?ids=abc&access_token={VALID_TOKEN}")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IDS"


def test_list_photos_with_empty_ids_returns_empty_list(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    override_seller_access(seller_id=5, published_by=1)
    client = TestClient(app)

    response = client.get(f"/api/v1/photos?ids=&access_token={VALID_TOKEN}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["photos"] == []

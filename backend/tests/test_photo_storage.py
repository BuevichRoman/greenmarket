import pytest

from app.platform.photo_storage import PhotoStorage, UnsupportedContentTypeError, build_photo_url


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.calls.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})


def test_upload_puts_object_in_bucket_and_returns_generated_key():
    client = FakeS3Client()
    storage = PhotoStorage(bucket="test-bucket", client=client)

    s3_key = storage.upload(b"fake-image-bytes", "image/jpeg")

    assert len(client.calls) == 1
    assert client.calls[0]["Bucket"] == "test-bucket"
    assert client.calls[0]["Key"] == s3_key
    assert client.calls[0]["Body"] == b"fake-image-bytes"
    assert client.calls[0]["ContentType"] == "image/jpeg"
    assert s3_key.endswith(".jpg")


def test_upload_generates_unique_keys_for_repeated_calls():
    client = FakeS3Client()
    storage = PhotoStorage(bucket="test-bucket", client=client)

    first = storage.upload(b"a", "image/png")
    second = storage.upload(b"b", "image/png")

    assert first != second
    assert first.endswith(".png") and second.endswith(".png")


def test_upload_rejects_unsupported_content_type():
    storage = PhotoStorage(bucket="test-bucket", client=FakeS3Client())

    with pytest.raises(UnsupportedContentTypeError):
        storage.upload(b"data", "application/pdf")


def test_region_is_passed_to_boto3_client_when_no_client_injected(monkeypatch):
    calls = []

    def fake_boto3_client(service_name, **kwargs):
        calls.append((service_name, kwargs))
        return FakeS3Client()

    monkeypatch.setattr("app.platform.photo_storage.boto3.client", fake_boto3_client)

    PhotoStorage(bucket="test-bucket", region="eu-north-1")

    assert calls == [("s3", {"region_name": "eu-north-1"})]


def test_build_photo_url_returns_standard_s3_pattern():
    url = build_photo_url("seller-products/abc.jpg", bucket="greenmarket-photos", region="eu-north-1")

    assert url == "https://greenmarket-photos.s3.eu-north-1.amazonaws.com/seller-products/abc.jpg"


def test_build_photo_url_uses_public_base_url_when_given():
    url = build_photo_url(
        "greenmarket/seller-products/abc.jpg",
        bucket="greenmarket-photos",
        region="eu-north-1",
        public_base_url="https://pub-example.r2.dev",
    )

    assert url == "https://pub-example.r2.dev/greenmarket/seller-products/abc.jpg"


def test_endpoint_url_is_passed_to_boto3_client_when_given(monkeypatch):
    calls = []

    def fake_boto3_client(service_name, **kwargs):
        calls.append((service_name, kwargs))
        return FakeS3Client()

    monkeypatch.setattr("app.platform.photo_storage.boto3.client", fake_boto3_client)

    PhotoStorage(bucket="test-bucket", region="auto", endpoint_url="https://account.r2.cloudflarestorage.com")

    assert calls == [("s3", {"region_name": "auto", "endpoint_url": "https://account.r2.cloudflarestorage.com"})]

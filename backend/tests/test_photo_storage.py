import pytest

from app.platform.photo_storage import PhotoStorage, UnsupportedContentTypeError


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

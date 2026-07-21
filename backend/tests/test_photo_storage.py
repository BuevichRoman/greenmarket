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

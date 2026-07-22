import uuid

import boto3

_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class UnsupportedContentTypeError(Exception):
    """content_type файла не входит в allowlist фотографий товара."""


class PhotoStorage:
    """Загружает файлы фотографий товаров в S3. Ключ (`s3_key`) — случайный
    UUID + расширение по content_type, не зависит от имени исходного файла
    продавца (нет коллизий, не раскрывает исходное имя файла).
    """

    def __init__(self, *, bucket: str, region: str | None = None, client=None):
        self.bucket = bucket
        self.client = client if client is not None else boto3.client("s3", region_name=region)

    def upload(self, file_bytes: bytes, content_type: str) -> str:
        extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type)
        if extension is None:
            raise UnsupportedContentTypeError(f"Неподдерживаемый тип файла '{content_type}'")

        s3_key = f"seller-products/{uuid.uuid4()}.{extension}"
        self.client.put_object(Bucket=self.bucket, Key=s3_key, Body=file_bytes, ContentType=content_type)
        return s3_key


def build_photo_url(s3_key: str, *, bucket: str, region: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"

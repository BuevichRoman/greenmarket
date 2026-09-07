"""Правила приёма файла фотографии — одни на все входы.

Загрузка из рабочей книги и загрузка из Seller Admin обязаны принимать и
отвергать одно и то же: расхождение здесь означало бы, что фотография,
отклонённая в одном интерфейсе, проходит в другом.
"""

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


class PhotoUploadError(Exception):
    """Файл не принят. Несёт готовый код ответа и код ошибки API."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def looks_like_declared_image(content_type: str, data: bytes) -> bool:
    """Совпадает ли содержимое файла с заявленным Content-Type.

    Проверяется сигнатура — первые байты формата. Заголовку запроса верить
    нельзя: переименованный .pdf или оборванная закачка приезжают как
    `image/jpeg` и до этой проверки уходили в S3, а ломались уже у покупателя,
    когда браузер не мог отрисовать картинку. Полноценный разбор изображения
    (Pillow) для этого не нужен и притащил бы зависимость ради одной проверки.
    """
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def read_validated_photo(file) -> bytes:
    """Читает загруженный файл и проверяет его. Порядок проверок значим.

    Тип идёт первым, размер вторым, содержимое третьим: обрезанный гигантский
    файл — это прежде всего превышение лимита, и ответ не должен зависеть от
    того, успел ли в него попасть заголовок формата.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise PhotoUploadError(415, "UNSUPPORTED_CONTENT_TYPE", f"Недопустимый тип файла '{file.content_type}'")

    # Читаем не больше лимита + 1 байт, чтобы никогда не держать в памяти
    # произвольно большое тело запроса до проверки размера.
    data = file.file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise PhotoUploadError(413, "FILE_TOO_LARGE", "Файл превышает допустимый размер 10 МБ")

    if not looks_like_declared_image(file.content_type, data):
        raise PhotoUploadError(422, "INVALID_IMAGE_PAYLOAD", f"Содержимое файла не является '{file.content_type}'")

    return data

# Photo Upload Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Продавец может загрузить несколько фото товара в S3 через новый REST endpoint и связать их с товаром при публикации каталога (колонка «Фото» в шаблоне) — цикл 1 из 3 фичи «карточка товара» (см. [design doc](../specs/2026-07-21-photo-upload-backend-design.md)).

**Architecture:** Новый endpoint `POST /api/v1/photos` кладёт файл в S3 и создаёт запись `Photo` (raw SQL через `PhotoGateway`, т.к. `Photo` — платформенная таблица, не ORM-модель). Новая обязательная колонка «Фото» в шаблоне (список `Photo.id` через `;`) проходит через весь Publication Pipeline: `StructureValidator` → `SemanticValidator` (проверка существования id) → `Mapper` (парсинг в `photo_ids: list[int]`) → `PublicationService` (синхронизирует `SellerProductPhoto`, ORM-таблицу). `TemplateVersion` бампается на `2.0` без поддержки старой версии.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (raw SQL для платформенных таблиц, ORM для GreenMarket-таблиц), boto3 (S3), pytest, MySQL 8.0.36.

---

## Перед стартом

Прочитать design doc целиком: [`docs/superpowers/specs/2026-07-21-photo-upload-backend-design.md`](../specs/2026-07-21-photo-upload-backend-design.md). Все пути ниже — относительно `backend/`, если не сказано иное.

---

### Task 1: Миграция `Photo.seller_id`

**Files:**
- Create: `database/migrations/010_alter_photo_add_seller.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- Источник: docs/superpowers/specs/2026-07-21-photo-upload-backend-design.md
-- Трассируемость: какой продавец загрузил фото через POST /api/v1/photos.
-- Не enforced ownership check (нет FK на Seller — тот же паттерн, что
-- SellerProduct.seller_id/CatalogPublication.seller_id, см. SellerGateway).

ALTER TABLE Photo
    ADD COLUMN seller_id BIGINT UNSIGNED NULL
        COMMENT 'Продавец, загрузивший фото (трассируемость, не FK)',
    ADD INDEX idx_Photo_seller (seller_id);
```

- [ ] **Step 2: Применить миграцию локально**

Run: `mysql -u root -p greenmarket < ../database/migrations/010_alter_photo_add_seller.sql`
Expected: без ошибок (Photo уже существует из миграции 004).

- [ ] **Step 3: Проверить структуру таблицы**

Run: `mysql -u root -p greenmarket -e "DESCRIBE Photo;"`
Expected: строка `seller_id | bigint unsigned | YES | MUL | NULL`

- [ ] **Step 4: Commit**

```bash
git add database/migrations/010_alter_photo_add_seller.sql
git commit -m "GreenMarket: миграция 010 — Photo.seller_id для трассируемости загрузок"
```

---

### Task 2: `PhotoGateway.create()` / `exists_all()`

**Files:**
- Modify: `app/platform/photo_gateway.py`
- Test: `tests/test_photo_gateway.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_photo_gateway.py`:

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest tests/test_photo_gateway.py -v`
Expected: FAIL с `AttributeError: 'PhotoGateway' object has no attribute 'create'`

- [ ] **Step 3: Реализовать `create()`/`exists_all()`**

Заменить содержимое `app/platform/photo_gateway.py` целиком:

```python
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class PhotoGateway:
    """Читает и пишет минимально необходимые платформенные данные Photo
    напрямую из БД (raw SQL, не ORM — см. app/infrastructure/models.py,
    комментарий про платформенные таблицы Seller/User/Photo). Anti-Corruption
    Layer, тот же паттерн, что SellerGateway.
    """

    def __init__(self, session: Session):
        self.session = session

    def list_by_seller_products(self, seller_product_ids: list[int]) -> dict[int, list[str]]:
        if not seller_product_ids:
            return {}
        stmt = text(
            "SELECT spp.seller_product_id, p.s3_key "
            "FROM SellerProductPhoto spp "
            "JOIN Photo p ON p.id = spp.photo_id "
            "WHERE spp.seller_product_id IN :seller_product_ids "
            "ORDER BY spp.seller_product_id, spp.sort_order"
        ).bindparams(bindparam("seller_product_ids", expanding=True))
        rows = self.session.execute(stmt, {"seller_product_ids": seller_product_ids}).all()
        result: dict[int, list[str]] = defaultdict(list)
        for seller_product_id, s3_key in rows:
            result[seller_product_id].append(s3_key)
        return dict(result)

    def create(self, *, s3_key: str, seller_id: int) -> int:
        result = self.session.execute(
            text("INSERT INTO Photo (s3_key, seller_id, created_at) VALUES (:s3_key, :seller_id, :created_at)"),
            {"s3_key": s3_key, "seller_id": seller_id, "created_at": datetime.now(timezone.utc)},
        )
        return result.lastrowid

    def exists_all(self, photo_ids: list[int]) -> bool:
        if not photo_ids:
            return True
        stmt = text("SELECT COUNT(*) FROM Photo WHERE id IN :photo_ids").bindparams(
            bindparam("photo_ids", expanding=True)
        )
        count = self.session.execute(stmt, {"photo_ids": photo_ids}).scalar_one()
        return count == len(set(photo_ids))
```

- [ ] **Step 4: Запустить тесты снова**

Run: `uv run pytest tests/test_photo_gateway.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add app/platform/photo_gateway.py tests/test_photo_gateway.py
git commit -m "GreenMarket: PhotoGateway.create()/exists_all() для загрузки фото"
```

---

### Task 3: Настройки и зависимость boto3

**Files:**
- Modify: `app/core/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Добавить boto3 в зависимости**

В `pyproject.toml`, в список `dependencies`, после `"python-multipart",`:

```toml
    "python-multipart",
    "boto3",
```

Run: `uv sync`
Expected: `boto3` устанавливается без ошибок.

- [ ] **Step 2: Добавить настройки S3**

В `app/core/config.py`, после `seller_access_tokens: str = "{}"`:

```python
    seller_access_tokens: str = "{}"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
```

- [ ] **Step 3: Обновить `.env.example`**

Добавить в конец файла:

```
# S3-бакет для фотографий товаров (POST /api/v1/photos). Учётные данные AWS
# берутся из стандартной цепочки boto3 (переменные окружения/~/.aws/credentials),
# не хранятся в .env.
S3_BUCKET=greenmarket-photos-dev
S3_REGION=us-east-1
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock app/core/config.py .env.example
git commit -m "GreenMarket: настройки S3 + зависимость boto3"
```

---

### Task 4: `PhotoStorage` (S3-клиент)

**Files:**
- Create: `app/platform/photo_storage.py`
- Test: `tests/test_photo_storage.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_photo_storage.py`:

```python
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
```

- [ ] **Step 2: Запустить, убедиться, что падает**

Run: `uv run pytest tests/test_photo_storage.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.platform.photo_storage'`

- [ ] **Step 3: Реализовать `PhotoStorage`**

Создать `app/platform/photo_storage.py`:

```python
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

    def __init__(self, *, bucket: str, client=None):
        self.bucket = bucket
        self.client = client if client is not None else boto3.client("s3")

    def upload(self, file_bytes: bytes, content_type: str) -> str:
        extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type)
        if extension is None:
            raise UnsupportedContentTypeError(f"Неподдерживаемый тип файла '{content_type}'")

        s3_key = f"seller-products/{uuid.uuid4()}.{extension}"
        self.client.put_object(Bucket=self.bucket, Key=s3_key, Body=file_bytes, ContentType=content_type)
        return s3_key
```

- [ ] **Step 4: Запустить тесты снова**

Run: `uv run pytest tests/test_photo_storage.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/platform/photo_storage.py tests/test_photo_storage.py
git commit -m "GreenMarket: PhotoStorage — загрузка фото в S3"
```

---

### Task 5: `POST /api/v1/photos`

**Files:**
- Create: `app/api/v1/photos_schemas.py`
- Create: `app/api/v1/photos.py`
- Modify: `app/main.py`
- Test: `tests/test_photos_api.py`

- [ ] **Step 1: Схемы ответа**

Создать `app/api/v1/photos_schemas.py`:

```python
from pydantic import BaseModel


class PhotoUploadResponse(BaseModel):
    photo_id: int
```

- [ ] **Step 2: Написать падающие тесты API**

Создать `tests/test_photos_api.py`:

```python
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
```

- [ ] **Step 3: Запустить, убедиться, что падает**

Run: `uv run pytest tests/test_photos_api.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.api.v1.photos'`

- [ ] **Step 4: Реализовать endpoint**

Создать `app/api/v1/photos.py`:

```python
import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.photos_schemas import PhotoUploadResponse
from app.api.v1.schemas import error_response
from app.core.config import settings
from app.infrastructure.database import get_session
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import PhotoStorage
from app.publication.seller_access import resolve_seller_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/photos", tags=["photos"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def get_photo_storage():
    """Переопределяется в тестах фейковым S3-клиентом. По умолчанию `None` —
    endpoint строит настоящий PhotoStorage (см. upload_photo ниже), тот же
    паттерн, что get_google_sheets_parser_resource в publications.py."""
    return None


def get_seller_access_resolver():
    return resolve_seller_access


@router.post("", response_model=PhotoUploadResponse, status_code=201)
def upload_photo(
    access_token: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    storage=Depends(get_photo_storage),
    resolve_access=Depends(get_seller_access_resolver),
):
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        return error_response(422, "UNSUPPORTED_CONTENT_TYPE", f"Недопустимый тип файла '{file.content_type}'")

    file_bytes = file.file.read()
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        return error_response(413, "FILE_TOO_LARGE", "Файл превышает допустимый размер 10 МБ")

    photo_storage = storage if storage is not None else PhotoStorage(bucket=settings.s3_bucket)
    s3_key = photo_storage.upload(file_bytes, file.content_type)
    photo_id = PhotoGateway(session).create(s3_key=s3_key, seller_id=access.seller_id)
    session.commit()

    logger.info("Фото загружено: seller_id=%s photo_id=%s", access.seller_id, photo_id)
    return PhotoUploadResponse(photo_id=photo_id)
```

- [ ] **Step 5: Подключить роутер в `app/main.py`**

Добавить импорт после `from app.api.v1.publications import router as publications_router`:

```python
from app.api.v1.photos import router as photos_router
```

Добавить после `app.include_router(publications_router)`:

```python
app.include_router(photos_router)
```

- [ ] **Step 6: Запустить тесты снова**

Run: `uv run pytest tests/test_photos_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Полный прогон backend-тестов на этом шаге**

Run: `uv run pytest`
Expected: все тесты проходят (никакие существующие эндпоинты/роутинг не задеты).

- [ ] **Step 8: Commit**

```bash
git add app/api/v1/photos.py app/api/v1/photos_schemas.py app/main.py tests/test_photos_api.py
git commit -m "GreenMarket: POST /api/v1/photos — загрузка фото продавца в S3"
```

---

### Task 6: Колонка «Фото» в `StructureValidator`

**Files:**
- Modify: `app/validation/structure_validator.py`
- Modify: `tests/test_structure_validator.py`

- [ ] **Step 1: Обновить контракт колонок и версию**

В `app/validation/structure_validator.py`, заменить:

```python
CATALOG_COLUMNS = [
    _Column("SellerProductId", required=False),
    _Column("Наименование продавца", required=True),
    _Column("Товарная группа GreenMarket", required=True),
    _Column("Товарная позиция GreenMarket", required=False),
    _Column("Цена", required=True),
    _Column("Единица продажи", required=True),
    _Column("Остаток", required=True),
    _Column("Описание", required=False),
    _Column("Дополнительные характеристики", required=False),
]
```

на:

```python
CATALOG_COLUMNS = [
    _Column("SellerProductId", required=False),
    _Column("Наименование продавца", required=True),
    _Column("Товарная группа GreenMarket", required=True),
    _Column("Товарная позиция GreenMarket", required=False),
    _Column("Цена", required=True),
    _Column("Единица продажи", required=True),
    _Column("Остаток", required=True),
    _Column("Описание", required=False),
    _Column("Дополнительные характеристики", required=False),
    _Column("Фото", required=True),
]
```

И заменить:

```python
SUPPORTED_TEMPLATE_VERSIONS = {"1.0"}
```

на:

```python
SUPPORTED_TEMPLATE_VERSIONS = {"2.0"}
```

- [ ] **Step 2: Обновить фикстуры теста под новую версию/колонку**

В `tests/test_structure_validator.py`:

Заменить `CATALOG_HEADER` (добавить «Фото» последней колонкой):

```python
CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `SYSTEM_ROWS`:

```python
SYSTEM_ROWS = [
    ["TemplateVersion", "2.0"],
    ["TemplateId", "template-1"],
]
```

Заменить строку каталога в `make_valid_workbook`:

```python
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, [1, "Яблоко", "Овощи", "Прочее", 100, "кг", 5, "", "", "1"]]),
```

Заменить `test_unsupported_template_version_reports_error` (было `"2.0"`, теперь это поддерживаемая версия — используем заведомо неподдерживаемую `"3.0"`):

```python
def test_unsupported_template_version_reports_error():
    rows = [["TemplateVersion", "3.0"] if row[0] == "TemplateVersion" else row for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("версия шаблона" in e.message for e in result.errors)
```

- [ ] **Step 3: Добавить тест на обязательность колонки «Фото»**

Добавить в конец файла:

```python
def test_missing_photo_column_reports_error():
    truncated = CATALOG_HEADER[:-1]  # без «Фото»
    workbook = replace_sheet(make_valid_workbook(), "Каталог", [truncated])

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("обязательная колонка 'Фото'" in e.message for e in result.errors)
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_structure_validator.py -v`
Expected: PASS (все тесты, включая новый)

- [ ] **Step 5: Commit**

```bash
git add app/validation/structure_validator.py tests/test_structure_validator.py
git commit -m "GreenMarket: колонка «Фото» в CATALOG_COLUMNS, TemplateVersion 2.0"
```

---

### Task 7: `photo_ids` в `Mapper`

**Files:**
- Modify: `app/mapping/publication_model.py`
- Modify: `app/mapping/mapper.py`
- Modify: `tests/test_mapper.py`

- [ ] **Step 1: Добавить поле в `PublicationProduct`**

В `app/mapping/publication_model.py`, добавить поле после `attributes: str | None`:

```python
@dataclass(frozen=True)
class PublicationProduct:
    seller_product_id: object | None
    seller_name: str
    product_group_name: str
    product_name: str | None
    price: float
    unit: str
    stock: float
    description: str | None
    attributes: str | None
    photo_ids: list[int]
```

- [ ] **Step 2: Обновить тестовые фикстуры (заранее, до реализации — тест должен упасть на новом поведении, а не на несуществующем поле)**

В `tests/test_mapper.py`:

Заменить `CATALOG_HEADER` (добавить «Фото»):

```python
CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `SYSTEM_ROWS`:

```python
SYSTEM_ROWS = [
    ["TemplateVersion", "2.0"],
    ["TemplateId", "template-1"],
]
```

Добавить 10-е значение `"5"` (единичный photo_id) в конец каждого из следующих row-литералов (10 мест): строки в `test_maps_single_valid_row_into_publication_product`, `test_maps_multiple_catalog_rows_in_order` (2 ряда), `test_ignores_reference_sheets_and_instruction_sheet`, `test_maps_system_sheet_and_seller_id_into_metadata` (пустой каталог — не требует правки), `test_raises_mapper_error_when_validation_result_has_errors`, `test_row_that_violates_the_validated_contract_raises_mapper_error_not_a_raw_exception`, `test_coerces_non_string_catalog_cells_to_str`, `test_hand_built_fixture_workbook_actually_passes_real_structure_validator`, `test_blank_string_cells_normalize_to_none` (см. ниже — там пустая строка, не число).

Конкретные замены:

```python
def test_maps_single_valid_row_into_publication_product():
    workbook = make_workbook([[1, "Ферма Иванова", "Овощи", "Морковь", 99.5, "кг", 10, "Свежая морковь", "Сорт: Нантская", "5"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert len(result.products) == 1
    product = result.products[0]
    assert product.seller_product_id == 1
    assert product.seller_name == "Ферма Иванова"
    assert product.product_group_name == "Овощи"
    assert product.product_name == "Морковь"
    assert product.price == 99.5
    assert product.unit == "кг"
    assert product.stock == 10
    assert product.description == "Свежая морковь"
    assert product.attributes == "Сорт: Нантская"
    assert product.photo_ids == [5]
```

```python
def test_maps_multiple_catalog_rows_in_order():
    workbook = make_workbook(
        [
            [1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"],
            [2, "Ферма Б", "Фрукты", "Яблоко", 80, "кг", 20, None, None, "2;3"],
        ]
    )

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert [p.seller_product_id for p in result.products] == [1, 2]
    assert [p.product_name for p in result.products] == ["Морковь", "Яблоко"]
    assert [p.photo_ids for p in result.products] == [[1], [2, 3]]
```

```python
def test_ignores_reference_sheets_and_instruction_sheet():
    extra = [
        RawSheet(name="Товарные группы", index=2, rows=[["1", None, "Овощи"]]),
        RawSheet(name="Товарные позиции", index=3, rows=[["1", "1", "Морковь"]]),
        RawSheet(name="Инструкция", index=4, rows=[["свободный текст"]]),
    ]
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]], extra_sheets=extra)

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert len(result.products) == 1
```

```python
def test_raises_mapper_error_when_validation_result_has_errors():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]])
    invalid_result = ValidationResult(errors=[ValidationError(sheet="Каталог", message="что-то не так")])

    with pytest.raises(MapperError):
        Mapper().map(workbook, invalid_result, seller_id=42)
```

```python
def test_row_that_violates_the_validated_contract_raises_mapper_error_not_a_raw_exception():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", None, "кг", 5, None, None, "1"]])

    with pytest.raises(MapperError):
        Mapper().map(workbook, VALID_RESULT, seller_id=42)
```

```python
def test_coerces_non_string_catalog_cells_to_str():
    workbook = make_workbook([[1, 777, "Овощи", "Морковь", 50, 7, 5, None, None, "1"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    product = result.products[0]
    assert product.seller_name == "777"
    assert product.unit == "7"
```

```python
def test_hand_built_fixture_workbook_actually_passes_real_structure_validator():
    from app.validation.structure_validator import StructureValidator

    full_workbook = make_workbook(
        [[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "1"]],
        extra_sheets=[
            RawSheet(name="Товарные группы", index=2, rows=[["ProductGroupId", "ParentProductGroupId", "Наименование"], [1, None, "Овощи"]]),
            RawSheet(name="Товарные позиции", index=3, rows=[["ProductId", "ProductGroupId", "Наименование"], [1, 1, "Морковь"]]),
            RawSheet(name="Инструкция", index=4, rows=[["свободный текст"]]),
        ],
    )

    assert StructureValidator().validate(full_workbook).is_valid
```

```python
def test_blank_string_cells_normalize_to_none():
    workbook = make_workbook([["", "Ферма А", "Овощи", "", 50, "кг", 5, "", "", ""]])

    product = Mapper().map(workbook, VALID_RESULT, seller_id=42).products[0]

    assert product.seller_product_id is None
    assert product.product_name is None
    assert product.description is None
    assert product.attributes is None
    assert product.photo_ids == []
```

Добавить новый тест в конец файла:

```python
def test_maps_semicolon_separated_photo_ids_in_order():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, "12;15;7"]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.products[0].photo_ids == [12, 15, 7]


def test_empty_photo_cell_maps_to_empty_list():
    workbook = make_workbook([[1, "Ферма А", "Овощи", "Морковь", 50, "кг", 5, None, None, None]])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.products[0].photo_ids == []
```

- [ ] **Step 3: Запустить тесты, убедиться, что падают**

Run: `uv run pytest tests/test_mapper.py -v`
Expected: FAIL — `PublicationProduct.__init__() missing 1 required positional argument: 'photo_ids'` (или похожая ошибка на `_COLUMN_INDEX["Фото"]` в `mapper.py`, если структура шаблона там ещё не знает колонку).

- [ ] **Step 4: Реализовать парсинг в `mapper.py`**

В `app/mapping/mapper.py`, добавить после `_COL_ATTRIBUTES = _COLUMN_INDEX["Дополнительные характеристики"]`:

```python
_COL_PHOTOS = _COLUMN_INDEX["Фото"]
```

Добавить функцию после `_to_str_or_none`:

```python
def _parse_photo_ids(value: object) -> list[int]:
    if value is None or value == "":
        return []
    return [int(part.strip()) for part in str(value).split(";") if part.strip()]
```

В `_map_row`, добавить `photo_ids=_parse_photo_ids(_cell(row, _COL_PHOTOS)),` последним аргументом конструктора `PublicationProduct(...)`.

- [ ] **Step 5: Запустить тесты снова**

Run: `uv run pytest tests/test_mapper.py -v`
Expected: PASS (все тесты)

- [ ] **Step 6: Commit**

```bash
git add app/mapping/publication_model.py app/mapping/mapper.py tests/test_mapper.py
git commit -m "GreenMarket: Mapper парсит колонку «Фото» в photo_ids"
```

---

### Task 8: Валидация «Фото» в `SemanticValidator`

**Files:**
- Modify: `app/validation/semantic_validator.py`
- Modify: `app/application/publication_use_case.py`
- Modify: `tests/test_semantic_validator.py`
- Modify: `tests/test_validator.py`

- [ ] **Step 1: Обновить фикстуры теста (падают первыми на новом конструкторе)**

В `tests/test_semantic_validator.py`, заменить импорты (добавить `PhotoGateway`):

```python
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.semantic_validator import SemanticValidator
from sqlalchemy import text
```

Заменить `HEADER` (добавить «Фото»):

```python
HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `make_validator`:

```python
def make_validator(session) -> SemanticValidator:
    return SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session))
```

Добавить helper после `make_validator`:

```python
def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid
```

Обновить каждую существующую строку каталога, добавив реальный `photo_id` последним элементом. Пример (повторить для всех 9 тестов с непустой строкой — `test_valid_row_has_no_errors`, `test_missing_required_field_reports_error`, `test_unknown_product_group_reports_error`, `test_product_from_a_different_group_reports_error`, `test_unknown_product_reports_error`, `test_other_product_placeholder_is_allowed`, `test_negative_price_reports_error`, `test_non_numeric_stock_reports_error`, `test_fully_empty_row_is_ignored`):

```python
def test_valid_row_has_no_errors(session):
    photo_id = insert_photo(session, s3_key="a.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid
```

```python
def test_missing_required_field_reports_error(session):
    photo_id = insert_photo(session, s3_key="b.jpg")
    workbook = make_workbook([[1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Наименование продавца" for e in result.errors)
```

```python
def test_unknown_product_group_reports_error(session):
    photo_id = insert_photo(session, s3_key="c.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Несуществующая группа", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующая группа" in e.message for e in result.errors)
```

```python
def test_product_from_a_different_group_reports_error(session):
    photo_id = insert_photo(session, s3_key="d.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Овощи", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Апельсин" in e.message for e in result.errors)
```

```python
def test_unknown_product_reports_error(session):
    photo_id = insert_photo(session, s3_key="e.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Несуществующий товар", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any("Несуществующий товар" in e.message for e in result.errors)
```

```python
def test_other_product_placeholder_is_allowed(session):
    photo_id = insert_photo(session, s3_key="f.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Прочее", 99.5, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid
```

```python
def test_negative_price_reports_error(session):
    photo_id = insert_photo(session, s3_key="g.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", -1, "кг", 10, "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Цена" for e in result.errors)
```

```python
def test_non_numeric_stock_reports_error(session):
    photo_id = insert_photo(session, s3_key="h.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", "много", "", "", str(photo_id)]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Остаток" for e in result.errors)
```

```python
def test_fully_empty_row_is_ignored(session):
    photo_a = insert_photo(session, s3_key="i.jpg")
    photo_b = insert_photo(session, s3_key="j.jpg")
    empty_row = [None] * len(HEADER)
    workbook = make_workbook(
        [
            [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_a)],
            empty_row,
            [2, "Лимоны оптом", "Цитрусовые", "Лимон", 79.0, "кг", 5, "", "", str(photo_b)],
        ]
    )

    result = make_validator(session).validate(workbook)

    assert result.is_valid
```

- [ ] **Step 2: Добавить новые тесты на валидацию «Фото»**

Добавить в конец файла:

```python
def test_missing_photo_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", ""]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_non_numeric_photo_id_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "not-a-number"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_nonexistent_photo_id_reports_error(session):
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "999999999"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_multiple_photo_ids_all_must_exist(session):
    photo_a = insert_photo(session, s3_key="k.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", f"{photo_a};999999999"]])

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Фото" for e in result.errors)


def test_multiple_valid_photo_ids_have_no_error(session):
    photo_a = insert_photo(session, s3_key="l.jpg")
    photo_b = insert_photo(session, s3_key="m.jpg")
    workbook = make_workbook([[1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", f"{photo_a};{photo_b}"]])

    result = make_validator(session).validate(workbook)

    assert result.is_valid
```

- [ ] **Step 3: Запустить тесты, убедиться, что падают**

Run: `uv run pytest tests/test_semantic_validator.py -v`
Expected: FAIL — `TypeError: SemanticValidator.__init__() missing 1 required positional argument: 'photo_gateway'`

- [ ] **Step 4: Реализовать валидацию в `semantic_validator.py`**

Заменить содержимое `app/validation/semantic_validator.py` целиком:

```python
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET

_COL_SELLER_NAME = 1
_COL_PRODUCT_GROUP = 2
_COL_PRODUCT = 3
_COL_PRICE = 4
_COL_UNIT = 5
_COL_STOCK = 6
_COL_PHOTOS = 9

_OTHER_PRODUCT_PLACEHOLDER = "Прочее"


def _cell(row: list[object], index: int) -> object:
    return row[index] if index < len(row) else None


def _row_is_empty(row: list[object]) -> bool:
    return all(cell is None or cell == "" for cell in row)


class SemanticValidator:
    """Проверяет значения строк листа «Каталог»: обязательные поля не пусты,
    цена/остаток — неотрицательные числа, товарная группа/позиция существуют
    в справочниках, идентификаторы фото («Фото») — целые числа, существующие
    в Photo. Не проверяет структуру (StructureValidator) и не проверяет
    бизнес-правила вроде дублей SellerProductId (BusinessValidator).
    """

    def __init__(
        self,
        product_group_repository: ProductGroupRepository,
        product_repository: ProductRepository,
        photo_gateway: PhotoGateway,
    ):
        self.product_group_repository = product_group_repository
        self.product_repository = product_repository
        self.photo_gateway = photo_gateway

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        if catalog is None or len(catalog.rows) < 2:
            return ValidationResult(errors=[])

        errors: list[ValidationError] = []
        for row_number, row in enumerate(catalog.rows[1:], start=2):
            if _row_is_empty(row):
                continue
            errors += self._validate_row(catalog.name, row_number, row)
        return ValidationResult(errors=errors)

    def _validate_row(self, sheet_name: str, row_number: int, row: list[object]) -> list[ValidationError]:
        errors: list[ValidationError] = []

        seller_name = _cell(row, _COL_SELLER_NAME)
        if not seller_name:
            errors.append(self._required_field_empty(sheet_name, row_number, "Наименование продавца"))

        group_name = _cell(row, _COL_PRODUCT_GROUP)
        group = None
        if not group_name:
            errors.append(self._required_field_empty(sheet_name, row_number, "Товарная группа GreenMarket"))
        else:
            group = self.product_group_repository.find_by_name(group_name)
            if group is None:
                errors.append(
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Товарная группа GreenMarket",
                        message=f"Товарная группа '{group_name}' не найдена",
                    )
                )

        product_name = _cell(row, _COL_PRODUCT)
        if product_name and product_name != _OTHER_PRODUCT_PLACEHOLDER and group is not None:
            products_in_group = {product.name for product in self.product_repository.list_by_group(group.id)}
            if product_name not in products_in_group:
                errors.append(
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Товарная позиция GreenMarket",
                        message=f"Товарная позиция '{product_name}' не найдена в группе '{group_name}'",
                    )
                )

        errors += self._validate_non_negative_number(sheet_name, row_number, "Цена", _cell(row, _COL_PRICE))

        if not _cell(row, _COL_UNIT):
            errors.append(self._required_field_empty(sheet_name, row_number, "Единица продажи"))

        errors += self._validate_non_negative_number(sheet_name, row_number, "Остаток", _cell(row, _COL_STOCK))

        errors += self._validate_photos(sheet_name, row_number, _cell(row, _COL_PHOTOS))

        return errors

    def _validate_photos(self, sheet_name: str, row_number: int, value: object) -> list[ValidationError]:
        if not value:
            return [self._required_field_empty(sheet_name, row_number, "Фото")]

        parts = [part.strip() for part in str(value).split(";") if part.strip()]
        if not parts:
            return [self._required_field_empty(sheet_name, row_number, "Фото")]

        photo_ids: list[int] = []
        for part in parts:
            try:
                photo_ids.append(int(part))
            except ValueError:
                return [
                    ValidationError(
                        sheet=sheet_name,
                        row=row_number,
                        column="Фото",
                        message=f"'{value}' содержит нечисловой идентификатор фото",
                    )
                ]

        if not self.photo_gateway.exists_all(photo_ids):
            return [
                ValidationError(
                    sheet=sheet_name,
                    row=row_number,
                    column="Фото",
                    message=f"Один или несколько идентификаторов фото не существуют: {value}",
                )
            ]
        return []

    def _validate_non_negative_number(self, sheet_name: str, row_number: int, column: str, value: object) -> list[ValidationError]:
        if value is None or value == "":
            return [self._required_field_empty(sheet_name, row_number, column)]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return [ValidationError(sheet=sheet_name, row=row_number, column=column, message=f"'{value}' не является числом")]
        if value < 0:
            return [ValidationError(sheet=sheet_name, row=row_number, column=column, message=f"Значение {value} не может быть отрицательным")]
        return []

    def _required_field_empty(self, sheet_name: str, row_number: int, column: str) -> ValidationError:
        return ValidationError(sheet=sheet_name, row=row_number, column=column, message="Обязательное поле пусто")
```

- [ ] **Step 5: Обновить конструктор в `publication_use_case.py`**

В `app/application/publication_use_case.py`, добавить импорт:

```python
from app.platform.photo_gateway import PhotoGateway
```

Заменить:

```python
        validator = Validator(
            StructureValidator(),
            SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
            BusinessValidator(),
        )
```

на:

```python
        validator = Validator(
            StructureValidator(),
            SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session)),
            BusinessValidator(),
        )
```

- [ ] **Step 6: Обновить `tests/test_validator.py`**

Заменить импорты (добавить `PhotoGateway`, `text`):

```python
from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.business_validator import BusinessValidator
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator
```

Заменить `CATALOG_HEADER`:

```python
CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `SYSTEM_ROWS`:

```python
SYSTEM_ROWS = [
    ["TemplateVersion", "2.0"],
    ["TemplateId", "template-1"],
]
```

Заменить `make_validator`:

```python
def make_validator(session) -> Validator:
    return Validator(
        StructureValidator(),
        SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session)),
        BusinessValidator(),
    )
```

Добавить helper после `make_validator`:

```python
def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid
```

Заменить `test_valid_workbook_end_to_end_has_no_errors`:

```python
def test_valid_workbook_end_to_end_has_no_errors(session):
    photo_id = insert_photo(session, s3_key="validator-1.jpg")
    row = [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)]
    workbook = make_valid_workbook(row)

    result = make_validator(session).validate(workbook)

    assert result.is_valid
```

Заменить `test_combines_semantic_and_business_errors_when_structure_is_valid`:

```python
def test_combines_semantic_and_business_errors_when_structure_is_valid(session):
    photo_id = insert_photo(session, s3_key="validator-2.jpg")
    rows = [
        [1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", str(photo_id)],
        [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 50, "кг", 5, "", "", str(photo_id)],
    ]
    workbook = RawWorkbook(
        source="valid.xlsx",
        sheets=[
            RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *rows]),
            RawSheet(name="Товарные группы", index=1, rows=[PRODUCT_GROUPS_HEADER]),
            RawSheet(name="Товарные позиции", index=2, rows=[PRODUCTS_HEADER]),
            RawSheet(name="Инструкция", index=3, rows=[["текст"]]),
            RawSheet(name="_System", index=4, rows=SYSTEM_ROWS),
        ],
    )

    result = make_validator(session).validate(workbook)

    assert not result.is_valid
    assert any(e.column == "Наименование продавца" for e in result.errors)
    assert any("SellerProductId 1" in e.message for e in result.errors)
```

- [ ] **Step 7: Запустить оба файла тестов**

Run: `uv run pytest tests/test_semantic_validator.py tests/test_validator.py -v`
Expected: PASS (все тесты)

- [ ] **Step 8: Commit**

```bash
git add app/validation/semantic_validator.py app/application/publication_use_case.py tests/test_semantic_validator.py tests/test_validator.py
git commit -m "GreenMarket: SemanticValidator проверяет колонку «Фото»"
```

---

### Task 9: `SellerProductPhotoRepository`

**Files:**
- Create: `app/infrastructure/repositories/seller_product_photo_repository.py`
- Test: `tests/test_seller_product_photo_repository.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_seller_product_photo_repository.py`:

```python
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
```

- [ ] **Step 2: Запустить, убедиться, что падает**

Run: `uv run pytest tests/test_seller_product_photo_repository.py -v`
Expected: FAIL с `ModuleNotFoundError`

- [ ] **Step 3: Реализовать репозиторий**

Создать `app/infrastructure/repositories/seller_product_photo_repository.py`:

```python
from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProductPhoto


class SellerProductPhotoRepository:
    def __init__(self, session: Session):
        self.session = session

    def replace_for_product(self, seller_product_id: int, photo_ids: list[int]) -> None:
        """Удаляет все существующие связи под seller_product_id и вставляет
        заново с sort_order = позиция в списке. Полная замена, не diff — набор
        фото на товар приходит одной публикацией целиком."""
        self.session.query(SellerProductPhoto).filter(
            SellerProductPhoto.seller_product_id == seller_product_id
        ).delete()
        for sort_order, photo_id in enumerate(photo_ids):
            self.session.add(
                SellerProductPhoto(seller_product_id=seller_product_id, photo_id=photo_id, sort_order=sort_order)
            )
        self.session.flush()

    def list_photo_ids(self, seller_product_id: int) -> list[int]:
        rows = (
            self.session.query(SellerProductPhoto.photo_id)
            .filter(SellerProductPhoto.seller_product_id == seller_product_id)
            .order_by(SellerProductPhoto.sort_order)
            .all()
        )
        return [row[0] for row in rows]
```

- [ ] **Step 4: Запустить тесты снова**

Run: `uv run pytest tests/test_seller_product_photo_repository.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/repositories/seller_product_photo_repository.py tests/test_seller_product_photo_repository.py
git commit -m "GreenMarket: SellerProductPhotoRepository — синхронизация фото товара"
```

---

### Task 10: Синхронизация фото в `PublicationService`

**Files:**
- Modify: `app/publication/publication_service.py`
- Modify: `tests/test_publication_service.py`

- [ ] **Step 1: Обновить фикстуры/факторки теста (падают на новом обязательном параметре конструктора)**

В `tests/test_publication_service.py`, добавить импорт:

```python
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
```

Заменить `make_service`:

```python
def make_service(session) -> PublicationService:
    return PublicationService(
        session=session,
        seller_gateway=SellerGateway(session),
        seller_product_repository=SellerProductRepository(session),
        product_repository=ProductRepository(session),
        product_group_repository=ProductGroupRepository(session),
        catalog_publication_repository=CatalogPublicationRepository(session),
        seller_product_photo_repository=SellerProductPhotoRepository(session),
    )
```

Заменить `make_product`:

```python
def make_product(*, seller_product_id=None, seller_name="Ферма А", group="Тестовая группа PublicationService", name=None, price=50.0, unit="кг", stock=5.0, description=None, attributes=None, photo_ids=None) -> PublicationProduct:
    return PublicationProduct(
        seller_product_id=seller_product_id,
        seller_name=seller_name,
        product_group_name=group,
        product_name=name,
        price=price,
        unit=unit,
        stock=stock,
        description=description,
        attributes=attributes,
        photo_ids=photo_ids if photo_ids is not None else [],
    )
```

В `test_integrity_error_race_on_publication_key_is_wrapped`, заменить прямую конструкцию `PublicationService(...)`:

```python
    service = PublicationService(
        session=committing_session,
        seller_gateway=SellerGateway(committing_session),
        seller_product_repository=SellerProductRepository(committing_session),
        product_repository=ProductRepository(committing_session),
        product_group_repository=ProductGroupRepository(committing_session),
        catalog_publication_repository=BlindToRaceRepository(committing_session),
        seller_product_photo_repository=SellerProductPhotoRepository(committing_session),
    )
```

- [ ] **Step 2: Добавить падающие тесты синхронизации фото**

Добавить в конец файла:

```python
def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid


def test_publish_links_photos_to_new_seller_product(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма с фото")
    user_id = insert_user(committing_session, name="Admin")
    photo_a = insert_photo(committing_session, s3_key="a.jpg")
    photo_b = insert_photo(committing_session, s3_key="b.jpg")
    service = make_service(committing_session)

    model = make_model(seller_id, [make_product(price=10, photo_ids=[photo_a, photo_b])])
    service.publish(model, published_by=user_id, publication_key="photo-key-1", catalog_hash="photo-hash-1")

    seller_product_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id
    linked = SellerProductPhotoRepository(committing_session).list_photo_ids(seller_product_id)
    assert linked == [photo_a, photo_b]


def test_republishing_replaces_photo_set(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма смена фото")
    user_id = insert_user(committing_session, name="Admin")
    photo_a = insert_photo(committing_session, s3_key="c.jpg")
    photo_b = insert_photo(committing_session, s3_key="d.jpg")
    photo_c = insert_photo(committing_session, s3_key="e.jpg")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(price=10, photo_ids=[photo_a, photo_b])])
    service.publish(first, published_by=user_id, publication_key="photo-key-a", catalog_hash="photo-hash-a")
    seller_product_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id

    second = make_model(seller_id, [make_product(seller_product_id=seller_product_id, price=10, photo_ids=[photo_c])])
    result = service.publish(second, published_by=user_id, publication_key="photo-key-b", catalog_hash="photo-hash-b")

    linked = SellerProductPhotoRepository(committing_session).list_photo_ids(seller_product_id)
    assert linked == [photo_c]
    assert result.updated_count == 1


def test_republishing_with_only_photos_changed_still_counts_as_updated(committing_session):
    # Регрессия на то, что _has_changed сравнивает только цену/остаток/etc —
    # публикация с той же ценой, но новым фото, обязана попасть в ветку
    # обновления, иначе SellerProductPhoto не синхронизируется.
    seller_id = insert_seller(committing_session, name="Ферма только фото")
    user_id = insert_user(committing_session, name="Admin")
    photo_a = insert_photo(committing_session, s3_key="f.jpg")
    photo_b = insert_photo(committing_session, s3_key="g.jpg")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(price=10, unit="кг", stock=5, photo_ids=[photo_a])])
    service.publish(first, published_by=user_id, publication_key="photo-key-c", catalog_hash="photo-hash-c")
    seller_product_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id

    second = make_model(
        seller_id, [make_product(seller_product_id=seller_product_id, price=10, unit="кг", stock=5, photo_ids=[photo_b])]
    )
    result = service.publish(second, published_by=user_id, publication_key="photo-key-d", catalog_hash="photo-hash-d")

    assert result.updated_count == 1
    assert SellerProductPhotoRepository(committing_session).list_photo_ids(seller_product_id) == [photo_b]
```

- [ ] **Step 3: Запустить, убедиться, что падают**

Run: `uv run pytest tests/test_publication_service.py -v`
Expected: FAIL — `TypeError: PublicationService.__init__() missing 1 required keyword-only argument: 'seller_product_photo_repository'`

- [ ] **Step 4: Обновить `PublicationService`**

В `app/publication/publication_service.py`, добавить импорт:

```python
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
```

Заменить `__init__`:

```python
    def __init__(
        self,
        session: Session,
        seller_gateway: SellerGateway,
        seller_product_repository: SellerProductRepository,
        product_repository: ProductRepository,
        product_group_repository: ProductGroupRepository,
        catalog_publication_repository: CatalogPublicationRepository,
        seller_product_photo_repository: SellerProductPhotoRepository,
    ):
        self.session = session
        self.seller_gateway = seller_gateway
        self.seller_product_repository = seller_product_repository
        self.product_repository = product_repository
        self.product_group_repository = product_group_repository
        self.catalog_publication_repository = catalog_publication_repository
        self.seller_product_photo_repository = seller_product_photo_repository
```

Заменить `_apply_catalog` целиком:

```python
    def _apply_catalog(self, products: list[PublicationProduct], seller_id: int) -> tuple[int, int, int]:
        existing_by_id = {sp.id: sp for sp in self.seller_product_repository.list_by_seller(seller_id)}
        # N+1 сознательно — размер каталога продавца на Stage 1 мал, не
        # оптимизируем заранее (YAGNI).
        existing_photo_ids_by_id = {
            sp_id: self.seller_product_photo_repository.list_photo_ids(sp_id) for sp_id in existing_by_id
        }
        seen_ids: set[int] = set()
        created = updated = 0

        for item in products:
            product_id = self._resolve_product_id(item)

            if item.seller_product_id is None:
                seller_product = self.seller_product_repository.create(
                    seller_id=seller_id,
                    product_id=product_id,
                    seller_name=item.seller_name,
                    price=item.price,
                    stock=item.stock,
                    unit=item.unit,
                    description=item.description,
                )
                self.seller_product_photo_repository.replace_for_product(seller_product.id, item.photo_ids)
                created += 1
                continue

            existing = existing_by_id.get(item.seller_product_id)
            if existing is None or existing.seller_id != seller_id:
                raise PublicationConflictError(
                    f"SellerProductId {item.seller_product_id} не найден среди товаров продавца {seller_id}"
                )

            seen_ids.add(existing.id)
            photos_changed = existing_photo_ids_by_id.get(existing.id, []) != item.photo_ids
            if self._has_changed(existing, item, product_id) or photos_changed:
                if existing.product_id != product_id:
                    existing.moderation_status = "WAIT_PRODUCT"
                    existing.moderator_id = None
                    existing.moderated_at = None
                    existing.moderation_comment = None
                existing.product_id = product_id
                existing.seller_name = item.seller_name
                existing.price = item.price
                existing.stock = item.stock
                existing.unit = item.unit
                existing.description = item.description
                existing.is_published = True
                self.seller_product_photo_repository.replace_for_product(existing.id, item.photo_ids)
                updated += 1

        deactivated = 0
        for seller_product in existing_by_id.values():
            if seller_product.id not in seen_ids and seller_product.is_published:
                seller_product.is_published = False
                deactivated += 1

        return created, updated, deactivated
```

- [ ] **Step 5: Запустить тесты снова**

Run: `uv run pytest tests/test_publication_service.py -v`
Expected: PASS (все тесты, включая 3 новых)

- [ ] **Step 6: Commit**

```bash
git add app/publication/publication_service.py tests/test_publication_service.py
git commit -m "GreenMarket: PublicationService синхронизирует SellerProductPhoto при публикации"
```

---

### Task 11: Ripple — оставшиеся тесты полного пайплайна

**Files:**
- Modify: `tests/test_publication_use_case.py`
- Modify: `tests/test_publications_api.py`
- Modify: `tests/test_catalog_template_builder.py`
- Modify: `tests/test_catalog_template_artifact.py`

- [ ] **Step 1: `tests/test_publication_use_case.py` — обновить фикстуры**

Заменить `CATALOG_HEADER`:

```python
CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `SYSTEM_ROWS`:

```python
SYSTEM_ROWS = [["TemplateVersion", "2.0"], ["TemplateId", "template-1"]]
```

Добавить helper после `insert_user`:

```python
def insert_photo(session, *, s3_key: str) -> int:
    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid
```

Заменить каждый вызов `make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", ""]])` (или с `-5` вместо `50`) на версию со вставленным фото и добавленным 10-м значением. Все пять тестов, использующих такую строку (`test_publishes_valid_catalog`, `test_validation_error_raises_with_error_list`, `test_republishing_same_content_is_idempotent_no_op`, `test_no_mode_row_defaults_to_prod_result`, `test_mode_test_writes_to_test_session_not_prod`):

```python
def test_publishes_valid_catalog(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма Use Case")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-1.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    result = use_case.publish("sheet-1", seller_id=seller_id, published_by=user_id)

    assert result.success is True
    assert result.created_count == 1
    assert result.publication_id > 0
```

```python
def test_validation_error_raises_with_error_list(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма невалидная")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-2.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    import pytest
    with pytest.raises(PublicationValidationError) as exc_info:
        use_case.publish("sheet-2", seller_id=seller_id, published_by=user_id)

    assert len(exc_info.value.validation_result.errors) > 0
```

```python
def test_republishing_same_content_is_idempotent_no_op(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма повтор")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-3.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    first = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)
    second = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)

    assert first.publication_key != second.publication_key
    assert (second.created_count, second.updated_count, second.deactivated_count) == (0, 0, 0)
```

```python
def test_no_mode_row_defaults_to_prod_result(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма без Mode")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="uc-4.jpg")
    resource = make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    result = use_case.publish("sheet-mode-default", seller_id=seller_id, published_by=user_id)

    assert result.mode == "prod"
```

```python
def test_mode_test_writes_to_test_session_not_prod(committing_session, test_committing_session):
    from app.infrastructure.repositories.seller_product_repository import SellerProductRepository

    seller_id = insert_seller(test_committing_session, name="Ферма TEST-режим")
    user_id = insert_user(test_committing_session, name="Admin")
    photo_id = insert_photo(test_committing_session, s3_key="uc-5.jpg")
    resource = make_resource(
        [[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]],
        system_rows=[*SYSTEM_ROWS, ["Mode", "TEST"]],
    )
    use_case = PublicationUseCase(committing_session, test_committing_session, parser_resource=resource)

    result = use_case.publish("sheet-mode-test", seller_id=seller_id, published_by=user_id)

    assert result.mode == "test"
    assert result.success is True
    seller_products = SellerProductRepository(test_committing_session).list_by_seller(seller_id)
    assert len(seller_products) == 1
```

`test_mode_test_without_configured_test_session_raises_clear_error` не трогать — падает раньше валидации каталога (нет сессии).

Добавить импорт `text` в начало файла, если ещё не импортирован (уже импортирован — используется в `insert_seller`/`insert_user`).

- [ ] **Step 2: Запустить**

Run: `uv run pytest tests/test_publication_use_case.py -v`
Expected: PASS (все тесты)

- [ ] **Step 3: `tests/test_publications_api.py` — обновить фикстуры**

Заменить `CATALOG_HEADER`:

```python
CATALOG_HEADER = [
    "SellerProductId",
    "Наименование продавца",
    "Товарная группа GreenMarket",
    "Товарная позиция GreenMarket",
    "Цена",
    "Единица продажи",
    "Остаток",
    "Описание",
    "Дополнительные характеристики",
    "Фото",
]
```

Заменить `SYSTEM_ROWS`:

```python
SYSTEM_ROWS = [["TemplateVersion", "2.0"], ["TemplateId", "template-1"]]
```

Добавить helper после `insert_user`:

```python
def insert_photo(session, *, s3_key: str) -> int:
    from sqlalchemy import text

    return session.execute(text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}).lastrowid
```

Заменить 5 вызовов `make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", ...]])` (строки 83, 109, 210, 231, 353 в исходном файле):

```python
def test_successful_publication_returns_200(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма API")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="api-1.jpg")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]]))
    client = TestClient(app)
    ...
```

(Тело теста после этих строк не меняется — только предшествующие строки конструирования ресурса.)

```python
def test_mode_test_publishes_to_test_session_and_reports_mode(committing_session, test_committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(test_committing_session, name="Ферма API тест-режим")
    user_id = insert_user(test_committing_session, name="Admin")
    photo_id = insert_photo(test_committing_session, s3_key="api-2.jpg")
    override_session(committing_session)
    override_test_session(test_committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(
        make_resource(
            [[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]],
            system_rows=[*SYSTEM_ROWS, ["Mode", "TEST"]],
        )
    )
    ...
```

```python
def test_validation_errors_return_422_with_details(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="api-3.jpg")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", "", str(photo_id)]]))
    ...
```

```python
def test_validation_errors_include_sheet_row_column(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации 2")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="api-4.jpg")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", -5, "кг", 5, "", "", str(photo_id)]]))
    ...
```

```python
def test_spreadsheet_id_is_extracted_from_sheet_url(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ссылка")
    user_id = insert_user(committing_session, name="Admin")
    photo_id = insert_photo(committing_session, s3_key="api-5.jpg")
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    override_resource(make_resource([[None, "Ферма А", "Цитрусовые", "Прочее", 50, "кг", 5, "", "", str(photo_id)]]))
    ...
```

Остальные тесты файла (`test_missing_or_invalid_access_token_returns_403`, `test_missing_sheet_source_returns_422`, `test_pydantic_type_error_returns_422_with_envelope`, `test_sheet_not_found_returns_404`, `test_sheet_access_denied_returns_403`, `test_generic_google_api_error_returns_500`, `test_unexpected_construction_failure_returns_500_internal_error`, `test_mode_test_without_test_session_returns_422`) не строят каталожную строку с данными (`[]` или падают раньше валидации) — не трогать.

- [ ] **Step 4: Запустить**

Run: `uv run pytest tests/test_publications_api.py -v`
Expected: PASS (все тесты)

- [ ] **Step 5: `tests/test_catalog_template_builder.py` — обновить два теста**

Заменить `test_catalog_sheet_has_autofilter_over_full_data_range` (10 колонок → последняя буква `J`, не `I`):

```python
def test_catalog_sheet_has_autofilter_over_full_data_range():
    wb = build_workbook()
    ws = wb[CATALOG_SHEET]
    last_row = max(ws.max_row, 1000)
    assert str(ws.auto_filter.ref) == f"A1:J{last_row}"
```

Заменить `test_build_workbook_accepts_prefilled_catalog_rows`:

```python
def test_build_workbook_accepts_prefilled_catalog_rows():
    row = [None, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "1"]
    wb = build_workbook(catalog_rows=[row])
    assert _sheet_values(wb[CATALOG_SHEET])[1] == row
```

- [ ] **Step 6: Запустить**

Run: `uv run pytest tests/test_catalog_template_builder.py -v`
Expected: FAIL на этом шаге — `test_column_hints_cover_exactly_the_catalog_columns` и `test_every_catalog_header_cell_has_a_comment` упадут, пока `COLUMN_HINTS["Фото"]` не добавлен (Task 12). Это ожидаемо — Task 12 идёт следующим и это чинит.

- [ ] **Step 7: `tests/test_catalog_template_artifact.py` — обновить фикстуры и добавить helper патчинга фото**

Заменить `_make_validator`:

```python
def _make_validator(session) -> Validator:
    return Validator(
        StructureValidator(),
        SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session)),
        BusinessValidator(),
    )
```

Добавить импорт `PhotoGateway` и `RawSheet`/`RawWorkbook`/`text`:

```python
from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.mapping.mapper import Mapper
from app.parsing.excel_parser import ExcelParser
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.platform.photo_gateway import PhotoGateway
from app.validation.business_validator import BusinessValidator
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import CATALOG_COLUMNS, CATALOG_SHEET, SYSTEM_SHEET, StructureValidator
from app.validation.validator import Validator
```

Заменить `test_master_template_retains_formatting_and_protection` (только autofilter-ассерт, `I1000` → `J1000`):

```python
    assert catalog_sheet.freeze_panes == "A2"
    assert str(catalog_sheet.auto_filter.ref) == "A1:J1000"
    assert catalog_sheet.column_dimensions["B"].width >= len("Наименование продавца") * 0.9
```

Добавить helper перед тестами полного пайплайна (после `_make_validator`):

```python
_PHOTO_COLUMN_INDEX = len(CATALOG_COLUMNS) - 1


def _with_real_photo_ids(workbook: RawWorkbook, session) -> RawWorkbook:
    """Примеры шаблона (.xlsx) хранят символические id в колонке «Фото»,
    которых нет в свежей БД теста/CI — подставляет реально вставленные Photo
    перед прогоном через SemanticValidator, не трогая остальные листы."""
    catalog = next(sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET)
    new_rows = [catalog.rows[0]]
    for row_index, row in enumerate(catalog.rows[1:]):
        photo_id = session.execute(
            text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": f"artifact-{workbook.source}-{row_index}.jpg"}
        ).lastrowid
        new_row = list(row)
        new_row[_PHOTO_COLUMN_INDEX] = str(photo_id)
        new_rows.append(new_row)
    patched_catalog = RawSheet(name=catalog.name, index=catalog.index, rows=new_rows)
    sheets = [patched_catalog if s.name == CATALOG_SHEET else s for s in workbook.sheets]
    return RawWorkbook(source=workbook.source, sheets=sheets)
```

Заменить `test_partial_example_passes_full_pipeline` и `test_full_example_passes_full_pipeline`:

```python
def test_partial_example_passes_full_pipeline(session):
    workbook = ExcelParser().parse(PARTIAL_EXAMPLE_PATH)
    workbook = _with_real_photo_ids(workbook, session)

    result = _make_validator(session).validate(workbook)
    assert result.is_valid, result.errors

    model = Mapper().map(workbook, result, seller_id=1)
    assert len(model.products) == 2


def test_full_example_passes_full_pipeline(session):
    workbook = ExcelParser().parse(FULL_EXAMPLE_PATH)
    workbook = _with_real_photo_ids(workbook, session)

    result = _make_validator(session).validate(workbook)
    assert result.is_valid, result.errors

    model = Mapper().map(workbook, result, seller_id=1)
    assert len(model.products) == 3
    assert model.products[2].product_name == "Прочее"
```

- [ ] **Step 8: Запустить (ожидаемо ещё падает на «Фото» в мастер-шаблоне — чинится Task 12)**

Run: `uv run pytest tests/test_catalog_template_artifact.py -v`
Expected: FAIL на `test_master_template_passes_structure_validation`/`test_master_template_retains_formatting_and_protection` (мастер `.xlsx` ещё не пересобран под новую колонку) — ожидаемо, чинится в Task 12.

- [ ] **Step 9: Commit (промежуточный — эта задача целиком закрывается только после Task 12, но код валиден и коммитим по мере готовности)**

```bash
git add tests/test_publication_use_case.py tests/test_publications_api.py tests/test_catalog_template_builder.py tests/test_catalog_template_artifact.py
git commit -m "GreenMarket: тесты полного пайплайна учитывают колонку «Фото» (TemplateVersion 2.0)"
```

---

### Task 12: Пересборка нормативного артефакта шаблона

**Files:**
- Modify: `app/catalog_template/data.py`
- Modify: `app/catalog_template/build_examples.py`
- Modify: `docs/02-domain/templates/catalog_template_v1.xlsx` (пересобранный бинарник)
- Modify: `docs/02-domain/templates/examples/catalog_template_v1_partial.xlsx` (пересобранный бинарник)
- Modify: `docs/02-domain/templates/examples/catalog_template_v1_full.xlsx` (пересобранный бинарник)

- [ ] **Step 1: Обновить `data.py`**

В `app/catalog_template/data.py`, заменить:

```python
TEMPLATE_VERSION = "1.0"
```

на:

```python
TEMPLATE_VERSION = "2.0"
```

В `COLUMN_WIDTHS`, добавить после `"Дополнительные характеристики": 32,`:

```python
    "Фото": 40,
```

В `COLUMN_HINTS`, добавить после подсказки `"Дополнительные характеристики"`:

```python
    "Фото": (
        "Список идентификаторов загруженных фотографий через `;` (например «12;15»). "
        "Заполняется автоматически карточкой товара — не редактируется вручную."
    ),
```

- [ ] **Step 2: Обновить примерные строки `build_examples.py`**

Добавить 10-е значение (плейсхолдер `"1"` — не проверяется этим скриптом, реальные id подставляются в тесте, см. Task 11 Step 7) в конец каждой строки `PARTIAL_ROWS`/`FULL_ROWS`:

```python
PARTIAL_ROWS = [
    [None, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "1"],
    [None, "Минеральная вода 'Летняя'", "Напитки", "", 45, "л", 50, "", "", "1"],
]

FULL_ROWS = [
    [
        None,
        "Апельсины оптом",
        "Цитрусовые",
        "Апельсин",
        99.5,
        "кг",
        10,
        "Свежие апельсины из Абхазии",
        "Сорт: Washington navel",
        "1",
    ],
    [
        None,
        "Молоко фермерское 3.2%",
        "Молоко",
        "Молоко",
        89,
        "л",
        30,
        "Цельное коровье молоко",
        "Жирность 3.2%",
        "1",
    ],
    [
        None,
        "Мандарины абхазские",
        "Цитрусовые",
        "Прочее",
        180,
        "кг",
        25,
        "Новый товар, ожидает модерации",
        "Сладкие, тонкая кожура",
        "1",
    ],
]
```

- [ ] **Step 3: Пересобрать нормативный артефакт и примеры**

Run: `uv run python -m app.catalog_template.build`
Expected: `Шаблон сохранён: .../catalog_template_v1.xlsx`

Run: `uv run python -m app.catalog_template.build_examples`
Expected: `Примеры сохранены: .../examples`

- [ ] **Step 4: Запустить весь набор тестов шаблона**

Run: `uv run pytest tests/test_catalog_template_builder.py tests/test_catalog_template_artifact.py tests/test_catalog_template_db_source.py -v`
Expected: PASS (все тесты, включая отложенные в Task 11 Step 6/8)

- [ ] **Step 5: Полный прогон всего backend-набора**

Run: `uv run pytest`
Expected: все тесты проходят.

- [ ] **Step 6: Commit**

```bash
git add app/catalog_template/data.py app/catalog_template/build_examples.py docs/02-domain/templates/catalog_template_v1.xlsx docs/02-domain/templates/examples/catalog_template_v1_partial.xlsx docs/02-domain/templates/examples/catalog_template_v1_full.xlsx
git commit -m "GreenMarket: TemplateVersion 2.0 — колонка «Фото» в шаблоне и примерах"
```

---

### Task 13: Документация

**Files:**
- Modify: `docs/02-domain/Catalog_Template.md`
- Modify: `docs/05-ui/Seller_Workspace.md`
- Modify: `docs/04-services/REST_API.md`

- [ ] **Step 1: `Catalog_Template.md` — новая колонка и версия**

В разделе «Структура рабочего каталога» → «Лист «Каталог»», заменить строку с пользовательскими полями:

```
**Пользовательские поля:** наименование продавца, товарная группа GreenMarket, товарная позиция GreenMarket, цена, единица продажи, остаток, описание, дополнительные характеристики, фото (список идентификаторов через `;`, заполняется автоматически карточкой товара — Apps Script, цикл 2).
```

Во всех местах, упоминающих `TemplateVersion`/`"1.0"` как текущую версию (раздел «Нормативный артефакт», «Процесс выпуска новой версии шаблона» — сама процедура остаётся, но пример версии актуализировать), заменить на `"2.0"`.

- [ ] **Step 2: `Seller_Workspace.md` — раздел 12**

В разделе 12 «Версионирование», добавить абзац:

```
**2026-07-21 (цикл 1 фичи «карточка товара»):** `TemplateVersion` повышен до `2.0` — добавлена обязательная колонка «Фото» (список идентификаторов загруженных фото через `;`) в лист «Каталог». Старая версия `1.0` не поддерживается параллельно (см. design doc цикла 1) — реальных продавцов на момент изменения не было. Колонка физически не защищена от редактирования продавцом в этом цикле — защита диапазона появится вместе с Apps Script (цикл 2), см. `docs/superpowers/specs/2026-07-21-photo-upload-backend-design.md`.
```

- [ ] **Step 3: `REST_API.md` — новый endpoint**

В разделе «Publication API», после `GET /api/v1/publications?access_token=...`, добавить:

```
- `POST /api/v1/photos` — загрузка фотографии товара. `Content-Type: multipart/form-data`, поля `access_token` (str) + `file` (изображение, `image/jpeg`/`image/png`/`image/webp`, до 10 МБ). Сервер резолвит `access_token` в `seller_id` (тот же `SELLER_ACCESS_TOKENS`, что и остальной Publication API), загружает файл в S3, создаёт запись `Photo`. Ответ `201` — `{"photo_id": int}`. Endpoint не связывает фото с товаром — связь появляется только при следующей публикации каталога через колонку «Фото» (см. `Catalog_Template.md`).
```

- [ ] **Step 4: Commit**

```bash
git add docs/02-domain/Catalog_Template.md docs/05-ui/Seller_Workspace.md docs/04-services/REST_API.md
git commit -m "GreenMarket: документация — колонка «Фото», TemplateVersion 2.0, POST /api/v1/photos"
```

---

## Итоговая проверка

- [ ] Run: `uv run pytest` — весь backend-набор зелёный.
- [ ] Run: `uv run python -m app.catalog_template.build && git status` — пересборка детерминирована, без незакоммиченных изменений бинарника.
- [ ] Ручная проверка: `curl -F "access_token=<реальный тестовый токен>" -F "file=@/path/to/photo.jpg" http://<host>/api/v1/photos` на dev-окружении с реальным S3-бакетом (не в CI) — вне охвата автотестов, отдельная ручная сверка перед тем, как цикл 2 (Apps Script) начнёт полагаться на этот endpoint.

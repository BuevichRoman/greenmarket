# Product Card Apps Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Продавец получает карточку товара внутри Google Sheets (меню «GreenMarket») — форма всех полей строки + управление фото (добавить/удалить/превью) — без ручного редактирования ячеек и без ручных вызовов API. Цикл 2 из 3 (см. [design doc](../specs/2026-07-22-product-card-apps-script-design.md)).

**Architecture:** Один маленький backend-эндпоинт (`GET /api/v1/photos` — batch-lookup URL по id, единственное отступление от «ноль backend-работы») + Apps Script, привязанный к рабочей книге продавца (Container-bound script): меню → модальное окно (`HtmlService`) с формой, `google.script.run` для вызовов сервера скрипта, `UrlFetchApp` для вызовов backend. `access_token` хранится в `PropertiesService`, не в `_System`.

**Tech Stack:** Python 3.13/FastAPI/SQLAlchemy (backend, как весь остальной проект), Google Apps Script (V8 runtime) + HTML/CSS/vanilla JS (карточка).

---

## Перед стартом

Прочитать design doc целиком: [`docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md`](../specs/2026-07-22-product-card-apps-script-design.md). Backend-пути ниже — относительно `backend/`. Apps Script пути — относительно корня репозитория.

---

### Task 1: `PhotoGateway.list_by_ids_and_seller()`

**Files:**
- Modify: `app/platform/photo_gateway.py`
- Test: `tests/test_photo_gateway.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_photo_gateway.py`:

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `uv run pytest tests/test_photo_gateway.py -v`
Expected: FAIL с `AttributeError: 'PhotoGateway' object has no attribute 'list_by_ids_and_seller'`

- [ ] **Step 3: Реализовать метод**

В `app/platform/photo_gateway.py`, добавить в класс `PhotoGateway` (после `exists_all`):

```python
    def list_by_ids_and_seller(self, photo_ids: list[int], seller_id: int) -> list[tuple[int, str]]:
        if not photo_ids:
            return []
        stmt = text(
            "SELECT id, s3_key FROM Photo WHERE id IN :photo_ids AND seller_id = :seller_id"
        ).bindparams(bindparam("photo_ids", expanding=True))
        rows = self.session.execute(stmt, {"photo_ids": photo_ids, "seller_id": seller_id}).all()
        return [(row[0], row[1]) for row in rows]
```

- [ ] **Step 4: Запустить тесты снова**

Run: `uv run pytest tests/test_photo_gateway.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add app/platform/photo_gateway.py tests/test_photo_gateway.py
git commit -m "GreenMarket: PhotoGateway.list_by_ids_and_seller() для GET /api/v1/photos"
```

---

### Task 2: `build_photo_url()`

**Files:**
- Modify: `app/platform/photo_storage.py`
- Test: `tests/test_photo_storage.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `tests/test_photo_storage.py`:

```python
def test_build_photo_url_returns_standard_s3_pattern():
    url = build_photo_url("seller-products/abc.jpg", bucket="greenmarket-photos", region="eu-north-1")

    assert url == "https://greenmarket-photos.s3.eu-north-1.amazonaws.com/seller-products/abc.jpg"
```

Обновить импорт в начале файла:

```python
from app.platform.photo_storage import PhotoStorage, UnsupportedContentTypeError, build_photo_url
```

- [ ] **Step 2: Запустить, убедиться, что падает**

Run: `uv run pytest tests/test_photo_storage.py -v`
Expected: FAIL с `ImportError: cannot import name 'build_photo_url'`

- [ ] **Step 3: Реализовать функцию**

В `app/platform/photo_storage.py`, добавить в конец файла (после класса `PhotoStorage`):

```python


def build_photo_url(s3_key: str, *, bucket: str, region: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
```

- [ ] **Step 4: Запустить тесты снова**

Run: `uv run pytest tests/test_photo_storage.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/platform/photo_storage.py tests/test_photo_storage.py
git commit -m "GreenMarket: build_photo_url() — публичный S3 URL по s3_key"
```

---

### Task 3: `GET /api/v1/photos`

**Files:**
- Modify: `app/api/v1/photos_schemas.py`
- Modify: `app/api/v1/photos.py`
- Test: `tests/test_photos_api.py`

- [ ] **Step 1: Схемы ответа**

В `app/api/v1/photos_schemas.py`, заменить содержимое целиком:

```python
from pydantic import BaseModel


class PhotoUploadResponse(BaseModel):
    photo_id: int


class PhotoInfo(BaseModel):
    photo_id: int
    url: str


class PhotoListResponse(BaseModel):
    photos: list[PhotoInfo]
```

- [ ] **Step 2: Написать падающие тесты**

Добавить в конец `tests/test_photos_api.py`:

```python
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
```

- [ ] **Step 3: Запустить, убедиться, что падают**

Run: `uv run pytest tests/test_photos_api.py -v`
Expected: FAIL — `404 Not Found` на GET-запросах (маршрута ещё нет).

- [ ] **Step 4: Реализовать endpoint**

В `app/api/v1/photos.py`, заменить импорт:

```python
from app.api.v1.photos_schemas import PhotoInfo, PhotoListResponse, PhotoUploadResponse
```

и

```python
from app.platform.photo_storage import PhotoStorage, build_photo_url
```

Добавить в конец файла:

```python


@router.get("", response_model=PhotoListResponse)
def list_photos(
    ids: str,
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
):
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        photo_ids = [int(part.strip()) for part in ids.split(",") if part.strip()]
    except ValueError:
        return error_response(422, "INVALID_IDS", f"'{ids}' содержит нечисловой идентификатор фото")

    rows = PhotoGateway(session).list_by_ids_and_seller(photo_ids, access.seller_id)
    photos = [
        PhotoInfo(photo_id=photo_id, url=build_photo_url(s3_key, bucket=settings.s3_bucket, region=settings.s3_region))
        for photo_id, s3_key in rows
    ]
    return PhotoListResponse(photos=photos)
```

- [ ] **Step 5: Запустить тесты снова**

Run: `uv run pytest tests/test_photos_api.py -v`
Expected: PASS (12 passed)

- [ ] **Step 6: Полный прогон backend-тестов**

Run: `uv run pytest`
Expected: все тесты проходят.

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/photos_schemas.py app/api/v1/photos.py tests/test_photos_api.py
git commit -m "GreenMarket: GET /api/v1/photos — batch-lookup URL фото по id"
```

---

### Task 4: Apps Script — проект и меню

**Files:**
- Create: `apps_script/product_card/appsscript.json`
- Create: `apps_script/product_card/Code.gs`

**Контекст:** дальше нет автоматических тестов — у Apps Script нет фреймворка юнит-тестов в этом проекте (см. design doc, раздел «Тестирование»). Каждый шаг — написать код, проверить синтаксис/логику вычитыванием, закоммитить. Полная ручная проверка всей карточки — Task 9.

- [ ] **Step 1: Манифест проекта**

Создать `apps_script/product_card/appsscript.json`:

```json
{
  "timeZone": "Europe/Moscow",
  "dependencies": {},
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "oauthScopes": [
    "https://www.googleapis.com/auth/spreadsheets.currentonly",
    "https://www.googleapis.com/auth/script.external_request",
    "https://www.googleapis.com/auth/script.container.ui"
  ]
}
```

- [ ] **Step 2: Константы и меню**

Создать `apps_script/product_card/Code.gs`:

```javascript
// GreenMarket Product Card — цикл 2 (docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md)
// Container-bound script: привязан к рабочей книге продавца (Seller Workspace).

var API_BASE_URL = 'https://CHANGE_ME.example.com/api/v1'; // TODO: заменить на реальный адрес backend перед деплоем

var CATALOG_SHEET_NAME = 'Каталог';
var GROUPS_SHEET_NAME = 'Товарные группы';
var PRODUCTS_SHEET_NAME = 'Товарные позиции';
var OTHER_PRODUCT_PLACEHOLDER = 'Прочее';
var ACCESS_TOKEN_PROPERTY = 'GREENMARKET_ACCESS_TOKEN';
var CURRENT_ROW_PROPERTY = 'GREENMARKET_CURRENT_ROW';

// Порядок точно соответствует CATALOG_COLUMNS в backend/app/validation/structure_validator.py —
// не менять без синхронной правки backend-контракта.
var COLUMN_ORDER = [
  'SellerProductId',
  'Наименование продавца',
  'Товарная группа GreenMarket',
  'Товарная позиция GreenMarket',
  'Цена',
  'Единица продажи',
  'Остаток',
  'Описание',
  'Дополнительные характеристики',
  'Фото',
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addToUi();
}

function openCardForSelectedRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var rowIndex = sheet.getActiveCell().getRow();
  if (rowIndex < 2) {
    SpreadsheetApp.getUi().alert('Выделите строку товара в листе «Каталог» (не строку заголовка).');
    return;
  }
  showCard(rowIndex);
}

function openCardForNewRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  showCard(sheet.getLastRow() + 1);
}

function showCard(rowIndex) {
  PropertiesService.getDocumentProperties().setProperty(CURRENT_ROW_PROPERTY, String(rowIndex));
  var html = HtmlService.createHtmlOutputFromFile('Card').setWidth(520).setHeight(640);
  SpreadsheetApp.getUi().showModalDialog(html, 'Карточка товара');
}
```

- [ ] **Step 3: Самопроверка**

Вычитать файл: `onOpen` вызывается автоматически Google Sheets при открытии книги (простой триггер — не требует OAuth-подтверждения сам по себе, оно запросится при первом реальном вызове `openCardForSelectedRow`/`openCardForNewRow`, которые используют `UrlFetchApp`/`PropertiesService` через дальнейшие задачи). Проверить, что `CATALOG_SHEET_NAME`/`GROUPS_SHEET_NAME`/`PRODUCTS_SHEET_NAME`/`OTHER_PRODUCT_PLACEHOLDER`/`COLUMN_ORDER` совпадают дословно (включая порядок) с `CATALOG_SHEET`/`PRODUCT_GROUPS_SHEET`/`PRODUCTS_SHEET`/`_OTHER_PRODUCT_PLACEHOLDER`/`CATALOG_COLUMNS` в `backend/app/validation/structure_validator.py`.

- [ ] **Step 4: Commit**

```bash
git add apps_script/product_card/appsscript.json apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — меню карточки товара (скелет проекта)"
```

---

### Task 5: Apps Script — чтение данных строки и справочников

**Files:**
- Modify: `apps_script/product_card/Code.gs`

- [ ] **Step 1: Добавить `getCardData`/`getReferenceLists`/`readColumnValues`/`parsePhotoIds`**

Добавить в конец `apps_script/product_card/Code.gs`:

```javascript

function getCardData() {
  var rowIndex = Number(PropertiesService.getDocumentProperties().getProperty(CURRENT_ROW_PROPERTY));
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var lastRow = sheet.getLastRow();
  var isNewRow = rowIndex > lastRow;

  var rawRow = isNewRow
    ? COLUMN_ORDER.map(function () { return ''; })
    : sheet.getRange(rowIndex, 1, 1, COLUMN_ORDER.length).getValues()[0];

  var fields = {};
  COLUMN_ORDER.forEach(function (name, i) { fields[name] = rawRow[i]; });

  var referenceLists = getReferenceLists();

  return {
    rowIndex: rowIndex,
    isNewRow: isNewRow,
    fields: fields,
    photoIds: parsePhotoIds(fields['Фото']),
    groups: referenceLists.groups,
    products: referenceLists.products,
  };
}

function getReferenceLists() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var groups = readColumnValues(ss.getSheetByName(GROUPS_SHEET_NAME), 3);
  var products = readColumnValues(ss.getSheetByName(PRODUCTS_SHEET_NAME), 3);
  products.push(OTHER_PRODUCT_PLACEHOLDER);
  return { groups: groups, products: products };
}

function readColumnValues(sheet, columnIndex) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  return sheet.getRange(2, columnIndex, lastRow - 1, 1).getValues()
    .map(function (row) { return row[0]; })
    .filter(function (value) { return value !== '' && value !== null; });
}

function parsePhotoIds(cellValue) {
  if (!cellValue) return [];
  return String(cellValue)
    .split(';')
    .map(function (part) { return part.trim(); })
    .filter(function (part) { return part !== ''; })
    .map(function (part) { return Number(part); });
}
```

- [ ] **Step 2: Самопроверка**

Вычитать: колонка 3 у листов «Товарные группы»/«Товарные позиции» — это «Наименование» (см. `PRODUCT_GROUPS_COLUMNS`/`PRODUCTS_COLUMNS` в `backend/app/validation/structure_validator.py`: `ProductGroupId`(1), `ParentProductGroupId`(2), `Наименование`(3); `ProductId`(1), `ProductGroupId`(2), `Наименование`(3)) — индекс `3` в `getReferenceLists` верный. `parsePhotoIds` — та же логика (split по `;`, trim, отбросить пустые, привести к числу), что `_parse_photo_ids` в `backend/app/mapping/mapper.py`, но без строгого приведения к `int` (JS `Number` на нечисловой строке даёт `NaN` — здесь это не страшно: карточка только показывает существующие данные, финальную валидацию делает `SemanticValidator` при публикации).

- [ ] **Step 3: Commit**

```bash
git add apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — чтение данных строки и справочников"
```

---

### Task 6: Apps Script — сохранение строки

**Files:**
- Modify: `apps_script/product_card/Code.gs`

- [ ] **Step 1: Добавить `saveRow`**

Добавить в конец `apps_script/product_card/Code.gs`:

```javascript

function saveRow(formData) {
  var rowIndex = Number(PropertiesService.getDocumentProperties().getProperty(CURRENT_ROW_PROPERTY));
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var existingSellerProductId = rowIndex <= sheet.getLastRow() ? sheet.getRange(rowIndex, 1).getValue() : '';

  var values = [
    existingSellerProductId, // Карточка никогда не пишет SellerProductId сама — служебное поле сервера.
    formData.sellerName,
    formData.productGroup,
    formData.productName,
    formData.price,
    formData.unit,
    formData.stock,
    formData.description,
    formData.attributes,
    formData.photoIds.join(';'),
  ];

  sheet.getRange(rowIndex, 1, 1, values.length).setValues([values]);
}
```

- [ ] **Step 2: Самопроверка**

Вычитать: `values` — ровно 10 элементов в том же порядке, что `COLUMN_ORDER`/`CATALOG_COLUMNS`. `existingSellerProductId` сохраняется как есть для существующей строки (карточка не меняет `SellerProductId`, это делает только сервер при публикации — см. `Catalog_Template.md`, «Добавление, изменение и удаление товаров»); для новой строки (`rowIndex > lastRow`) остаётся пустым, что и требуется для распознавания «новый товар» при следующей публикации.

- [ ] **Step 3: Commit**

```bash
git add apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — сохранение карточки в строку листа «Каталог»"
```

---

### Task 7: Apps Script — access_token и обработка ответов API

**Files:**
- Modify: `apps_script/product_card/Code.gs`

- [ ] **Step 1: Добавить `getOrPromptAccessToken`/`handleApiResponse`**

Добавить в конец `apps_script/product_card/Code.gs`:

```javascript

function getOrPromptAccessToken() {
  var props = PropertiesService.getDocumentProperties();
  var token = props.getProperty(ACCESS_TOKEN_PROPERTY);
  if (token) return token;

  var ui = SpreadsheetApp.getUi();
  var result = ui.prompt(
    'Токен доступа',
    'Введите access_token продавца (тот же, что для публикации каталога в личном кабинете):',
    ui.ButtonSet.OK_CANCEL
  );
  if (result.getSelectedButton() !== ui.Button.OK) return null;

  token = result.getResponseText().trim();
  if (!token) return null;

  props.setProperty(ACCESS_TOKEN_PROPERTY, token);
  return token;
}

function handleApiResponse(response, expectedStatus) {
  var code = response.getResponseCode();
  var body = JSON.parse(response.getContentText());
  if (code === expectedStatus) return body;

  if (code === 403) {
    PropertiesService.getDocumentProperties().deleteProperty(ACCESS_TOKEN_PROPERTY);
  }
  var message = (body.error && body.error.message) || ('Ошибка сервера (' + code + ')');
  throw new Error(message);
}
```

- [ ] **Step 2: Самопроверка**

Вычитать: при `403` токен удаляется из `PropertiesService` — следующий вызов любой функции, использующей `getOrPromptAccessToken()`, заново запросит токен у продавца (см. design doc, раздел «Обработка ошибок»); текущий вызов всё равно завершается ошибкой (`throw new Error(...)`) — продавцу нужно повторить действие («Добавить фото»/«Сохранить») после ввода нового токена. Формат ошибки backend (`{"error": {"code": ..., "message": ...}}`, см. `app/api/v1/schemas.py::error_response`) совпадает с тем, что читает `body.error.message`.

- [ ] **Step 3: Commit**

```bash
git add apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — хранение access_token, обработка ответов API"
```

---

### Task 8: Apps Script — загрузка фото и получение превью

**Files:**
- Modify: `apps_script/product_card/Code.gs`

- [ ] **Step 1: Добавить `uploadPhoto`/`getPhotoUrls`**

Добавить в конец `apps_script/product_card/Code.gs`:

```javascript

function uploadPhoto(base64Data, contentType, filename) {
  var accessToken = getOrPromptAccessToken();
  if (!accessToken) {
    throw new Error('Не указан access_token — загрузка отменена.');
  }

  var bytes = Utilities.base64Decode(base64Data);
  var blob = Utilities.newBlob(bytes, contentType, filename || 'photo');

  var response = UrlFetchApp.fetch(API_BASE_URL + '/photos', {
    method: 'post',
    payload: {
      access_token: accessToken,
      file: blob,
    },
    muteHttpExceptions: true,
  });

  return handleApiResponse(response, 201).photo_id;
}

function getPhotoUrls(photoIds) {
  if (!photoIds || photoIds.length === 0) return [];

  var accessToken = getOrPromptAccessToken();
  if (!accessToken) {
    throw new Error('Не указан access_token — превью недоступно.');
  }

  var url = API_BASE_URL + '/photos?ids=' + photoIds.join(',') + '&access_token=' + encodeURIComponent(accessToken);
  var response = UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true });
  return handleApiResponse(response, 200).photos;
}
```

- [ ] **Step 2: Самопроверка**

Вычитать: `UrlFetchApp.fetch` с `payload`, содержащим `Blob` (`file: blob`), Apps Script автоматически кодирует запрос как `multipart/form-data` — ручная сборка multipart-тела не нужна (идиоматичный способ загрузки файлов в Apps Script, не требует явного указания `boundary`/`Content-Type` заголовка). Ответ `POST /api/v1/photos` — `{"photo_id": int}` (см. `PhotoUploadResponse`), `handleApiResponse(response, 201).photo_id` читает это поле напрямую. Ответ `GET /api/v1/photos` — `{"photos": [{"photo_id", "url"}]}` (см. `PhotoListResponse`), `.photos` — соответствующий массив.

- [ ] **Step 3: Commit**

```bash
git add apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — загрузка фото и получение превью через backend"
```

---

### Task 9: Apps Script — форма карточки (Card.html)

**Files:**
- Create: `apps_script/product_card/Card.html`

- [ ] **Step 1: Создать файл**

Создать `apps_script/product_card/Card.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <style>
    body { font-family: Arial, sans-serif; padding: 12px; }
    label { display: block; margin-top: 10px; font-weight: bold; }
    input[type="text"], input[type="number"], select, textarea {
      width: 100%; padding: 6px; box-sizing: border-box; margin-top: 4px;
    }
    .photos { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .photo-thumb { position: relative; width: 80px; height: 80px; }
    .photo-thumb img { width: 100%; height: 100%; object-fit: cover; border-radius: 4px; }
    .photo-thumb button {
      position: absolute; top: -6px; right: -6px; background: #d33; color: #fff;
      border: none; border-radius: 50%; width: 20px; height: 20px; cursor: pointer;
    }
    .actions { margin-top: 16px; display: flex; gap: 8px; }
    button.primary { background: #2a7a2a; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
    button.secondary { background: #eee; border: 1px solid #ccc; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
    #status { margin-top: 10px; color: #888; font-size: 12px; }
  </style>
</head>
<body>
  <div id="form">
    <label>Наименование продавца</label>
    <input type="text" id="sellerName">

    <label>Товарная группа GreenMarket</label>
    <select id="productGroup"></select>

    <label>Товарная позиция GreenMarket</label>
    <select id="productName"></select>

    <label>Цена</label>
    <input type="number" id="price" step="0.01">

    <label>Единица продажи</label>
    <input type="text" id="unit">

    <label>Остаток</label>
    <input type="number" id="stock" step="0.001">

    <label>Описание</label>
    <textarea id="description" rows="2"></textarea>

    <label>Дополнительные характеристики</label>
    <textarea id="attributes" rows="2"></textarea>

    <label>Фото</label>
    <div class="photos" id="photos"></div>
    <input type="file" id="photoInput" accept="image/jpeg,image/png,image/webp" style="margin-top: 8px;">

    <div class="actions">
      <button class="primary" onclick="saveRow()">Сохранить</button>
      <button class="secondary" onclick="google.script.host.close()">Отмена</button>
    </div>
    <div id="status"></div>
  </div>

  <script>
    var photoIds = [];
    var photoPreviews = {};

    function setStatus(text) {
      document.getElementById('status').textContent = text || '';
    }

    function renderPhotos() {
      var container = document.getElementById('photos');
      container.innerHTML = '';
      photoIds.forEach(function (id) {
        var wrap = document.createElement('div');
        wrap.className = 'photo-thumb';
        var img = document.createElement('img');
        img.src = photoPreviews[id] || '';
        var btn = document.createElement('button');
        btn.textContent = '×';
        btn.onclick = function () { removePhoto(id); };
        wrap.appendChild(img);
        wrap.appendChild(btn);
        container.appendChild(wrap);
      });
    }

    function removePhoto(id) {
      photoIds = photoIds.filter(function (x) { return x !== id; });
      delete photoPreviews[id];
      renderPhotos();
    }

    function fillForm(data) {
      var f = data.fields;
      document.getElementById('sellerName').value = f['Наименование продавца'] || '';
      document.getElementById('price').value = f['Цена'] || '';
      document.getElementById('unit').value = f['Единица продажи'] || '';
      document.getElementById('stock').value = f['Остаток'] || '';
      document.getElementById('description').value = f['Описание'] || '';
      document.getElementById('attributes').value = f['Дополнительные характеристики'] || '';

      var groupSelect = document.getElementById('productGroup');
      data.groups.forEach(function (g) {
        var opt = document.createElement('option');
        opt.value = g;
        opt.textContent = g;
        groupSelect.appendChild(opt);
      });
      groupSelect.value = f['Товарная группа GreenMarket'] || '';

      var productSelect = document.getElementById('productName');
      data.products.forEach(function (p) {
        var opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p;
        productSelect.appendChild(opt);
      });
      productSelect.value = f['Товарная позиция GreenMarket'] || '';

      photoIds = data.photoIds.slice();
      if (photoIds.length > 0) {
        setStatus('Загрузка превью фото…');
        google.script.run
          .withSuccessHandler(function (photos) {
            photos.forEach(function (p) { photoPreviews[p.photo_id] = p.url; });
            renderPhotos();
            setStatus('');
          })
          .withFailureHandler(function (err) {
            setStatus('');
            alert('Не удалось загрузить превью фото: ' + err.message);
            renderPhotos();
          })
          .getPhotoUrls(photoIds);
      }
    }

    document.getElementById('photoInput').addEventListener('change', function (e) {
      var file = e.target.files[0];
      if (!file) return;

      var reader = new FileReader();
      reader.onload = function () {
        var base64 = reader.result.split(',')[1];
        var localPreviewUrl = URL.createObjectURL(file);
        setStatus('Загрузка фото…');
        google.script.run
          .withSuccessHandler(function (photoId) {
            photoIds.push(photoId);
            photoPreviews[photoId] = localPreviewUrl;
            renderPhotos();
            setStatus('');
            document.getElementById('photoInput').value = '';
          })
          .withFailureHandler(function (err) {
            setStatus('');
            alert('Ошибка загрузки фото: ' + err.message);
            document.getElementById('photoInput').value = '';
          })
          .uploadPhoto(base64, file.type, file.name);
      };
      reader.readAsDataURL(file);
    });

    function saveRow() {
      var formData = {
        sellerName: document.getElementById('sellerName').value,
        productGroup: document.getElementById('productGroup').value,
        productName: document.getElementById('productName').value,
        price: document.getElementById('price').value,
        unit: document.getElementById('unit').value,
        stock: document.getElementById('stock').value,
        description: document.getElementById('description').value,
        attributes: document.getElementById('attributes').value,
        photoIds: photoIds,
      };
      setStatus('Сохранение…');
      google.script.run
        .withSuccessHandler(function () {
          google.script.host.close();
        })
        .withFailureHandler(function (err) {
          setStatus('');
          alert('Ошибка сохранения: ' + err.message);
        })
        .saveRow(formData);
    }

    setStatus('Загрузка данных…');
    google.script.run
      .withSuccessHandler(function (data) {
        fillForm(data);
        setStatus('');
      })
      .withFailureHandler(function (err) {
        setStatus('');
        alert('Ошибка загрузки карточки: ' + err.message);
      })
      .getCardData();
  </script>
</body>
</html>
```

- [ ] **Step 2: Самопроверка**

Вычитать: все идентификаторы серверных функций, вызываемых через `google.script.run` (`getCardData`, `getPhotoUrls`, `uploadPhoto`, `saveRow`), совпадают с именами функций, добавленных в `Code.gs` в задачах 5–8. Поля `formData`, передаваемые в `saveRow`, совпадают по именам с тем, что `saveRow` в `Code.gs` ожидает (`sellerName`, `productGroup`, `productName`, `price`, `unit`, `stock`, `description`, `attributes`, `photoIds`). Ключи объекта `f` в `fillForm` (`f['Наименование продавца']` и т.д.) совпадают с ключами `fields`, которые строит `getCardData` из `COLUMN_ORDER`.

- [ ] **Step 3: Commit**

```bash
git add apps_script/product_card/Card.html
git commit -m "GreenMarket: Apps Script — форма карточки товара (Card.html)"
```

---

### Task 10: Деплой, ручное тестирование, документация

**Files:**
- Create: `apps_script/product_card/README.md`
- Modify: `docs/05-ui/Seller_Workspace_UX.md`

- [ ] **Step 1: README с инструкцией деплоя и чек-листом ручного тестирования**

Создать `apps_script/product_card/README.md`:

```markdown
# Product Card Apps Script — деплой и тестирование

Карточка товара продавца (цикл 2 фичи «карточка товара», см.
`docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md`).
Container-bound Google Apps Script — привязывается к конкретной рабочей
книге продавца (или к мастер-шаблону перед выпуском новой копии).

## Деплой (ручной, тулинга/clasp нет)

1. Открыть рабочую книгу (`catalog_template_v1.xlsx`, импортированную в Google
   Sheets, либо уже существующую копию продавца).
2. `Расширения → Apps Script` — откроется Script Editor привязанного проекта
   (если ещё не создан — Google создаст пустой проект автоматически).
3. Заменить содержимое `appsscript.json` (иконка шестерёнки слева →
   `Показать файл манифеста`) на содержимое `apps_script/product_card/appsscript.json`
   из этого репозитория.
4. Создать/заменить файл `Code.gs` — вставить содержимое
   `apps_script/product_card/Code.gs`.
5. В строке `API_BASE_URL` заменить `https://CHANGE_ME.example.com/api/v1` на
   реальный адрес backend.
6. Создать HTML-файл `Card` (`Файл → Создать → HTML-файл`, имя ровно `Card`) —
   вставить содержимое `apps_script/product_card/Card.html`.
7. Сохранить проект (`Ctrl+S`/`Cmd+S`), закрыть Script Editor, обновить страницу
   таблицы — в меню должен появиться пункт «GreenMarket».

## Ручное тестирование (чек-лист)

- [ ] При открытии книги в меню есть «GreenMarket» → «Открыть карточку» / «Добавить товар».
- [ ] «Открыть карточку» на строке заголовка (строка 1) — предупреждение, карточка не открывается.
- [ ] «Открыть карточку» на пустой строке без данных — карточка открывается, поля пустые.
- [ ] «Открыть карточку» на заполненной строке — все поля (наименование, группа, позиция, цена,
      единица, остаток, описание, характеристики) заполнены значениями из ячеек; если в
      ячейке «Фото» есть id — превью загружаются.
- [ ] «Добавить товар» — карточка открывается пустой; после «Сохранить» — новая строка
      добавляется в конец листа «Каталог» с корректными значениями.
- [ ] При первом действии (сохранение/загрузка фото) карточка запрашивает `access_token` —
      всплывающее окно `ui.prompt`; повторные действия токен уже не запрашивают.
- [ ] «Добавить фото» — выбор файла (jpg/png/webp) → превью появляется, файл реально
      загружен (проверить `GET /api/v1/publications`-совместимый способ или напрямую в БД/S3,
      что `Photo` с этим `s3_key` создан и привязан к `seller_id` продавца).
- [ ] «Удалить» на превью — фото пропадает из карточки; после «Сохранить» — id пропадает из
      ячейки «Фото» (публикация синхронизирует `SellerProductPhoto` без него).
- [ ] Загрузка файла неподдерживаемого типа (например `.pdf`) — сообщение об ошибке
      (`alert`), карточка остаётся открытой, остальные данные не потеряны.
- [ ] Ввод заведомо неверного `access_token` — любое действие возвращает читаемую ошибку
      (`SELLER_ACCESS_DENIED`), карточка предлагает ввести токен заново при следующем действии.
- [ ] После «Сохранить» с реальными данными — публикация каталога (`POST /api/v1/publications`)
      проходит без ошибок валидации по колонке «Фото».

## Инфраструктурное предусловие

S3-бакет (`S3_BUCKET`/`S3_REGION` в `.env` backend) должен быть публичным на чтение —
иначе превью в карточке и `GET /api/v1/photos` вернут URL, которые не откроются в
браузере. Настройка — на AWS-консоли, вне этого репозитория.
```

- [ ] **Step 2: Кросс-ссылка в Seller_Workspace_UX.md**

В `docs/05-ui/Seller_Workspace_UX.md`, добавить новый раздел в конец файла (после последнего существующего раздела):

```

## 11. Карточка товара (Apps Script, опционально)

Помимо прямого редактирования ячеек листа «Каталог» (разделы выше), продавец может
использовать карточку товара — меню «GreenMarket» → «Открыть карточку»/«Добавить товар»,
модальное окно с формой всех полей строки и управлением фото (добавить/удалить). Карточка
не меняет структуру рабочей книги и не заменяет прямое редактирование — это ускоряющая
надстройка поверх него. Полное описание архитектуры, деплоя и ручного тестирования —
`apps_script/product_card/README.md` и
`docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md`.
```

- [ ] **Step 3: Ручное сквозное тестирование**

Пройти чек-лист из `apps_script/product_card/README.md` целиком на реальной тестовой
рабочей книге (копия `catalog_template_v1.xlsx`, привязанный тестовый S3-бакет,
тестовый `access_token` из `SELLER_ACCESS_TOKENS`). Зафиксировать результат (все пункты
пройдены / список расхождений) перед коммитом.

- [ ] **Step 4: Commit**

```bash
git add apps_script/product_card/README.md docs/05-ui/Seller_Workspace_UX.md
git commit -m "GreenMarket: деплой Apps Script карточки, чек-лист тестирования, кросс-ссылка в UX-доке"
```

---

## Итоговая проверка

- [ ] Run: `uv run pytest` (из `backend/`) — весь backend-набор зелёный, включая новые тесты `GET /api/v1/photos`.
- [ ] Пройден чек-лист ручного тестирования Apps Script (`apps_script/product_card/README.md`) на реальной таблице.
- [ ] S3-бакет подтверждённо публичен на чтение (иначе превью не откроются) — инфраструктурный шаг вне кода.

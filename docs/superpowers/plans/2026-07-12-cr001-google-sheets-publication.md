# CR-001 + PR-007: Static Google Sheets Template → Publication REST API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Excel-generated `_System` publication contract with CR-001's static-template model (server-generated `PublicationKey`/`CatalogHash`, no document round-trip), then ship PR-007: `GoogleSheetsParser` + `POST /api/v1/publications` reading a seller's Google Sheets catalog via Service Account.

**Architecture:** `GoogleSheetsParser` (new, same `RawWorkbook` contract as `ExcelParser`) → `HashCalculator` (new, computes `CatalogHash` from parsed content) → `Validator` (reworked: `_System` now only carries template metadata) → `Mapper` (reworked: no longer reads `PublicationKey`/`CatalogHash`) → `PublicationService` (reworked: takes `publication_key`/`catalog_hash` as explicit server-generated inputs) → new `PublicationUseCase` orchestrates all of it → new FastAPI controller at `POST /api/v1/publications`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, pytest, `google-api-python-client` + `google-auth` + `google-auth-httplib2` (new).

**Source of truth for this plan:** `kwork/` conversation with colleague (three ChatGPT links resolved into CR-001), `docs/04-services/REST_API.md` (error envelope, HTTP codes), existing merged code in `backend/app/{parsing,validation,mapping,publication}`.

---

## Why each existing component changes (read this before Task 3)

The old model: server generates the Excel document, bakes `PublicationKey`/`CatalogHash` into its `_System` sheet, seller edits and re-submits, server compares. CR-001 replaces this because Google Sheets is a **static template the seller copies themselves** — GreenMarket never writes to it, so it can never contain server-issued per-publication values.

New model (CR-001, accepted by colleague):
- `PublicationKey` — generated fresh by the server on every `POST /publications` call (`uuid.uuid4()`, matches `CHAR(36)` column in migration 005). Lives only in `CatalogPublication`/`Seller.current_publication_key`.
- `CatalogHash` — computed by the server (`HashCalculator`) from the parsed `RawWorkbook`, **before** `Validator` runs, so it depends only on document content, not on validity. SHA-256 hex digest — matches `CHAR(64)` column in migration 005.
- `_System` sheet — no longer carries per-publication data. Shrinks to `TemplateVersion` + `TemplateId` (template metadata only). `StructureValidator` still requires the sheet, but checks different fields.
- `BusinessValidator._validate_publication_key` — deleted outright. Its only remaining job (`SellerProductId` duplicate check) needs neither `seller_id` nor `SellerGateway` — so `BusinessValidator` loses its constructor dependency, and `Validator.validate()` loses its `seller_id` parameter (nothing downstream in `Validator`/`BusinessValidator` needs it anymore; `Mapper.map()` keeps its own explicit `seller_id` param, unaffected).
- `PublicationMetadata` — drops `document_id`/`document_version`/`publication_key`/`generated_at`/`generated_by`/`catalog_hash` (none of these exist in the new `_System` anymore); gains `template_version`/`template_id`.
- `PublicationService.publish()` — gains explicit `publication_key`/`catalog_hash` keyword parameters (server-computed, passed in by the new Use Case) instead of reading them off `model.metadata`.
- `PublicationResult` — gains `publication_id` (the `CatalogPublication.id` row, needed by the REST response `publication_id` field — not present in the current dataclass).

## Open assumption flagged for colleague (does not block work, document like PR-004/005/006 precedent)

Exact `CatalogHash` scope isn't specified by CR-001 beyond "computed from `RawWorkbook` content." This plan hashes the **data rows of the `Каталог` sheet only** (header excluded, row order preserved) via SHA-256 over UTF-8 JSON (`json.dumps(rows, ensure_ascii=False, default=str)`). Document this in `backend/README.md` under "Отклонения и допущения" per Task 13 — same treatment as the open `CatalogHash`-algorithm question left by PR-004.

## Testing caveat for `GoogleSheetsParser` (flag to Roman, don't silently skip)

Every other integration test in this codebase hits real MySQL, never mocks (project convention, `backend/README.md`). Google Sheets API cannot be hit for free/offline here, and colleague's own spec expects a **real test spreadsheet shared to the Service Account** for true integration tests — infrastructure only Roman/colleague can provide (credentials, spreadsheet ID). This plan therefore:
- Gives `GoogleSheetsParser` an injectable `resource` seam (constructor param) so unit tests can pass a small hand-built fake Sheets API object (`FakeSheetsResource`, Task 10) instead of a mock library — verifies error-mapping and `RawWorkbook` shaping without network access.
- Does **not** write a real-network integration test against Google Sheets. If Roman provides `GOOGLE_SERVICE_ACCOUNT_FILE` + a real shared test spreadsheet ID later, add `test_google_sheets_parser_integration.py` following the `test_product_repository.py` pattern (skipped/failing without the real resource, same as DB-dependent tests already do).

---

### Task 1: ADR-0002 — record CR-001

**Files:**
- Create: `docs/06-development/adr/0002-static-google-sheets-template.md`

- [ ] **Step 1: Write the ADR**

```markdown
# 0002. Переход от генерируемого Excel к статическому шаблону Google Sheets (CR-001)

**Дата:** 2026-07-12
**Статус:** Принято

## Контекст

При переходе Publication Pipeline на Google Sheets как единственный источник
публикации Stage 1 обнаружено архитектурное противоречие: модель `_System`
унаследована от сценария, где GreenMarket сам генерирует рабочий каталог
(Excel) и вписывает в него служебные данные конкретной публикации
(`PublicationKey`, `CatalogHash`). Google Sheets в Stage 1 — статический
шаблон, который продавец копирует себе сам («Создать копию шаблона» →
заполнить → расшарить на Service Account → опубликовать); GreenMarket
никогда не пишет в таблицу (ни автоматического создания, ни обратной
синхронизации). Следовательно, сервер не может заранее вписать в документ
значения, которые сам же должен потом сверить.

## Решение

1. **`PublicationKey`** становится внутренним идентификатором публикации
   GreenMarket: генерируется сервером на каждый вызов `POST /publications`
   (`uuid.uuid4()`), хранится только в `CatalogPublication` и
   `Seller.current_publication_key`. Документ Google Sheets о нём не знает.
2. **`CatalogHash`** вычисляется сервером (`HashCalculator`) из содержимого
   `RawWorkbook`, полученного `GoogleSheetsParser`, — до `Validator`, чтобы
   зависеть только от содержимого документа, а не от результата валидации.
   Документ `CatalogHash` тоже не содержит.
3. **Лист `_System`** перестаёт хранить данные конкретной публикации.
   Минимальный состав — `TemplateVersion`, `TemplateId` (метаданные шаблона).
   `StructureValidator` продолжает требовать лист, но проверяет только эти
   поля.
4. **`StructureValidator`/`Mapper`** перестают читать из `_System`
   `PublicationKey`/`CatalogHash` — этих полей там больше нет.
5. **`BusinessValidator._validate_publication_key`** удаляется целиком —
   сверять в документе больше нечего. Оставшаяся проверка (дубли
   `SellerProductId`) не требует ни `seller_id`, ни `SellerGateway`.
6. **`PublicationService.publish()`** получает `publication_key`/
   `catalog_hash` явными параметрами от вызывающего кода (новый
   `PublicationUseCase`), а не из `PublicationModel.metadata`.
7. Google Sheets — источник публикации, не зеркало состояния GreenMarket.
   Обратная синхронизация в Stage 1 не реализуется.

## Последствия

- Требуются изменения в уже смёрженных PR-004 (`StructureValidator`,
  `BusinessValidator`), PR-005 (`Mapper`, `PublicationMetadata`), PR-006
  (`PublicationService.publish()`, `PublicationResult`) — не только новый
  PR-007.
- Обновляются нормативные документы: `Catalog_Template.md`,
  `Publication_Model.md`, `Publication_Service.md`, `REST_API.md`.
- Excel в будущем — отдельный `Parser`, работающий уже по этой (новой)
  модели публикации, а не по старой генерируемой.
- `Validator.validate()` теряет параметр `seller_id` (ничего в
  `Validator`/`BusinessValidator` больше в нём не нуждается; `Mapper.map()`
  сохраняет собственный явный параметр `seller_id`, не затронут).

## Связанные документы

`docs/02-domain/Catalog_Template.md`, `docs/02-domain/Publication_Model.md`,
`docs/04-services/Publication_Service.md`, `docs/04-services/REST_API.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/06-development/adr/0002-static-google-sheets-template.md
git commit -m "docs: add ADR-0002 for CR-001 (static Google Sheets template)"
```

---

### Task 2: Update normative docs for CR-001

**Files:**
- Modify: `docs/02-domain/Catalog_Template.md`
- Modify: `docs/02-domain/Publication_Model.md`
- Modify: `docs/04-services/Publication_Service.md`
- Modify: `docs/04-services/REST_API.md`

- [ ] **Step 1: `Catalog_Template.md` — replace Excel-generated model with static Google Sheets template**

In the "Назначение" section, replace:
```
В Stage 1 шаблон реализован как файл Microsoft Excel или Google Sheets — продавец работает с ним локально, затем публикует новую редакцию одной кнопкой.
```
with:
```
В Stage 1 шаблон реализован как статическая таблица Google Sheets, предоставляемая GreenMarket. Продавец создаёт собственную копию шаблона, заполняет её и публикует, указав ссылку на таблицу — GreenMarket читает её через Service Account и никогда не пишет в неё (см. CR-001, `docs/06-development/adr/0002-static-google-sheets-template.md`).
```

In "Архитектурные принципы", replace:
```
Рабочий каталог всегда создаётся сервером. После каждой успешной публикации формируется новая актуальная редакция, которую продавец скачивает для дальнейшей работы.
```
with:
```
Рабочий каталог (шаблон) создаётся продавцом как копия статического шаблона GreenMarket — сервер документ не генерирует и не обновляет его после публикации (CR-001). Обратная синхронизация в Stage 1 не реализуется: Google Sheets — источник публикации, не зеркало состояния GreenMarket.
```

Replace the "Лист `_System`" section:
```
### Лист `_System`

Служебная информация документа: `DocumentId`, `DocumentVersion`, `PublicationKey`, `GeneratedAt`, `GeneratedBy`, `CatalogHash`. Формируется сервером, продавцом не редактируется и не отображается в обычном режиме просмотра.
```
with:
```
### Лист `_System`

Метаданные шаблона (не конкретной публикации, CR-001): `TemplateVersion`, `TemplateId`. Продавцом не редактируется. `PublicationKey`/`CatalogHash` в документе не хранятся — оба генерируются сервером при публикации (см. `docs/04-services/Publication_Service.md`).
```

Replace the entire "PublicationKey" section body with:
```
## PublicationKey

`PublicationKey` — внутренний идентификатор конкретной публикации GreenMarket (CR-001). Генерируется сервером при каждом успешном вызове `POST /api/v1/publications`, хранится в `CatalogPublication.publication_key` и `Seller.current_publication_key`. Документ Google Sheets не содержит `PublicationKey` и не участвует в его генерации или проверке.
```

- [ ] **Step 2: `Publication_Model.md` — update "Источник данных"**

Replace:
```
Единственным источником данных является рабочий каталог продавца. Поддерживаются форматы Microsoft Excel и Google Sheets (через экспорт в Excel) — точный формат определён в [Catalog_Template.md](Catalog_Template.md). Publication Service не предоставляет интерфейс ручного редактирования каталога.
```
with:
```
Единственным источником данных является статическая таблица Google Sheets, созданная продавцом как копия шаблона GreenMarket (CR-001, [`docs/06-development/adr/0002-static-google-sheets-template.md`](../06-development/adr/0002-static-google-sheets-template.md)) — точный формат определён в [Catalog_Template.md](Catalog_Template.md). Publication Service не предоставляет интерфейс ручного редактирования каталога и не пишет в исходную таблицу.
```

- [ ] **Step 3: `Publication_Service.md` — update "Источник данных" + add Google Sheets Parser section**

Replace:
```
Источник данных только один — рабочий каталог продавца. Поддерживаются Microsoft Excel и Google Sheets (после экспорта в Excel); точный формат файла — [Catalog_Template.md](../02-domain/Catalog_Template.md). Ручное изменение опубликованного каталога через интерфейс не допускается.
```
with:
```
Источник данных только один — статическая таблица Google Sheets, созданная продавцом как копия шаблона GreenMarket (CR-001); точный формат — [Catalog_Template.md](../02-domain/Catalog_Template.md). Ручное изменение опубликованного каталога через интерфейс не допускается.

### Google Sheets Parser

`GoogleSheetsParser` читает таблицу через Service Account (`spreadsheets.values.batchGet`, `valueRenderOption=UNFORMATTED_VALUE` — обязательное условие эквивалентности `ExcelParser`). Таймаут запроса к Google API — 10 секунд, без retry в Stage 1 (публикация — синхронное пользовательское действие; лучше быстрый отказ, чем зависший HTTP-запрос). Контракт `GoogleSheetsParser` идентичен `ExcelParser` — возвращает тот же `RawWorkbook`, не вычисляет `PublicationKey`/`CatalogHash`.

### PublicationKey и CatalogHash — генерация сервером

`PublicationKey` (`uuid.uuid4()`) и `CatalogHash` (SHA-256 от содержимого `RawWorkbook`, посчитанный до `Validator`) больше не читаются из документа — оба генерируются/вычисляются сервером на каждый вызов публикации (CR-001).
```

- [ ] **Step 4: `REST_API.md` — Publication API becomes JSON, not multipart**

Replace:
```
- `POST /api/v1/publications` — создание публикации (Excel-файл + `publication_key`). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации, либо список ошибок валидации (`422`).
```
with:
```
- `POST /api/v1/publications` — создание публикации. `Content-Type: application/json`, тело `{"seller_id": int, "published_by": int, "sheet_url": str}` (либо `spreadsheet_id` вместо `sheet_url`, если клиент уже разобрал ссылку). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации (`publication_id`, `created`, `updated`, `deactivated`), либо список ошибок валидации (`422`).
```

- [ ] **Step 5: Commit**

```bash
git add docs/02-domain/Catalog_Template.md docs/02-domain/Publication_Model.md docs/04-services/Publication_Service.md docs/04-services/REST_API.md
git commit -m "docs: update Catalog_Template/Publication_Model/Publication_Service/REST_API for CR-001"
```

---

### Task 3: `HashCalculator` (new)

**Files:**
- Create: `backend/app/publication/hash_calculator.py`
- Test: `backend/tests/test_hash_calculator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hash_calculator.py
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.publication.hash_calculator import HashCalculator


def make_workbook(catalog_rows: list[list[object]]) -> RawWorkbook:
    header = ["SellerProductId", "Наименование продавца", "Цена"]
    return RawWorkbook(source="sheet", sheets=[RawSheet(name="Каталог", index=0, rows=[header, *catalog_rows])])


def test_same_content_produces_same_hash():
    workbook = make_workbook([[1, "Ферма А", 50]])

    first = HashCalculator().compute(workbook)
    second = HashCalculator().compute(make_workbook([[1, "Ферма А", 50]]))

    assert first == second


def test_different_content_produces_different_hash():
    a = HashCalculator().compute(make_workbook([[1, "Ферма А", 50]]))
    b = HashCalculator().compute(make_workbook([[1, "Ферма А", 99]]))

    assert a != b


def test_row_order_affects_hash():
    a = HashCalculator().compute(make_workbook([[1, "A", 50], [2, "B", 60]]))
    b = HashCalculator().compute(make_workbook([[2, "B", 60], [1, "A", 50]]))

    assert a != b


def test_header_row_is_excluded_from_hash():
    # Заголовок не данные каталога — смена заголовка не должна менять хеш.
    header_a = RawSheet(name="Каталог", index=0, rows=[["X", "Y", "Z"], [1, "A", 50]])
    header_b = RawSheet(name="Каталог", index=0, rows=[["SellerProductId", "Наименование продавца", "Цена"], [1, "A", 50]])

    a = HashCalculator().compute(RawWorkbook(source="s", sheets=[header_a]))
    b = HashCalculator().compute(RawWorkbook(source="s", sheets=[header_b]))

    assert a == b


def test_missing_catalog_sheet_does_not_crash():
    workbook = RawWorkbook(source="s", sheets=[])

    result = HashCalculator().compute(workbook)

    assert isinstance(result, str) and len(result) == 64


def test_hash_is_sha256_hex_digest_length():
    result = HashCalculator().compute(make_workbook([[1, "A", 50]]))

    assert len(result) == 64
    int(result, 16)  # не бросает — валидный hex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_hash_calculator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.publication.hash_calculator'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/publication/hash_calculator.py
import hashlib
import json

from app.parsing.raw_workbook import RawWorkbook
from app.validation.structure_validator import CATALOG_SHEET


class HashCalculator:
    """Вычисляет CatalogHash — SHA-256 от содержимого листа «Каталог»
    (без заголовка). Вызывается сразу после Parser, до Validator (CR-001) —
    хеш должен зависеть только от содержимого документа, не от результата
    валидации.
    """

    def compute(self, workbook: RawWorkbook) -> str:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        rows = catalog.rows[1:] if catalog and catalog.rows else []
        payload = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_hash_calculator.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/publication/hash_calculator.py backend/tests/test_hash_calculator.py
git commit -m "feat: add HashCalculator computing CatalogHash from RawWorkbook (CR-001)"
```

---

### Task 4: `StructureValidator` — `_System` becomes template-only

**Files:**
- Modify: `backend/app/validation/structure_validator.py:17,48-49,120-127`
- Modify: `backend/tests/test_structure_validator.py`

- [ ] **Step 1: Update the test fixture and assertions first (TDD — this test currently passes against the OLD contract; rewrite it to assert the NEW one, then watch it fail)**

Replace `SYSTEM_ROWS` and the system-field-related tests in `backend/tests/test_structure_validator.py`:

```python
SYSTEM_ROWS = [
    ["TemplateVersion", "1.0"],
    ["TemplateId", "template-1"],
]
```

Replace `test_missing_system_field_reports_error`:
```python
def test_missing_system_field_reports_error(self):
    pass
```
with:
```python
def test_missing_system_field_reports_error():
    rows_without_template_id = [row for row in SYSTEM_ROWS if row[0] != "TemplateId"]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows_without_template_id)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("TemplateId" in e.message for e in result.errors)
```

Replace `test_unsupported_template_version_reports_error` body (field name changes from `DocumentVersion` to `TemplateVersion`):
```python
def test_unsupported_template_version_reports_error():
    rows = [["TemplateVersion", "2.0"] if row[0] == "TemplateVersion" else row for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("версия шаблона" in e.message for e in result.errors)
```

Replace `test_empty_publication_key_value_reports_error` (PublicationKey no longer exists in `_System` at all — replace with the equivalent check on `TemplateVersion`):
```python
def test_empty_template_version_value_reports_error():
    rows = [["TemplateVersion", None] if row[0] == "TemplateVersion" else row for row in SYSTEM_ROWS]
    workbook = replace_sheet(make_valid_workbook(), "_System", rows)

    result = StructureValidator().validate(workbook)

    assert not result.is_valid
    assert any("TemplateVersion" in e.message for e in result.errors)
```

`test_narrow_system_sheet_does_not_crash` stays as-is (structurally identical — narrows whatever `SYSTEM_ROWS` currently is).

- [ ] **Step 2: Run test to verify it fails against the still-old implementation**

Run: `cd backend && uv run pytest tests/test_structure_validator.py -v`
Expected: FAIL — old `SYSTEM_FIELDS` still expects `DocumentId`/`PublicationKey`/etc., so `TemplateId`-only fixture reports the OLD fields as missing instead of the new ones.

- [ ] **Step 3: Update `structure_validator.py`**

In `backend/app/validation/structure_validator.py`, replace:
```python
SYSTEM_FIELDS = ["DocumentId", "DocumentVersion", "PublicationKey", "GeneratedAt", "GeneratedBy", "CatalogHash"]
```
with:
```python
SYSTEM_FIELDS = ["TemplateVersion", "TemplateId"]
```

Replace the version check inside `_validate_system_sheet`:
```python
        version = values.get("DocumentVersion")
```
with:
```python
        version = values.get("TemplateVersion")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_structure_validator.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/validation/structure_validator.py backend/tests/test_structure_validator.py
git commit -m "refactor: _System sheet carries only TemplateVersion/TemplateId (CR-001)"
```

---

### Task 5: `BusinessValidator` — drop `PublicationKey` check and `SellerGateway` dependency

**Files:**
- Modify: `backend/app/validation/business_validator.py`
- Modify: `backend/tests/test_business_validator.py` (full rewrite — no longer needs a DB session)

- [ ] **Step 1: Rewrite the test file first (no more `session`/`SellerGateway` — pure unit test)**

```python
# backend/tests/test_business_validator.py
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.validation.business_validator import BusinessValidator

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
]


def make_workbook(catalog_rows: list[list[object]]) -> RawWorkbook:
    return RawWorkbook(source="test", sheets=[RawSheet(name="Каталог", index=0, rows=[CATALOG_HEADER, *catalog_rows])])


def test_unique_seller_product_ids_have_no_error():
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [2, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert result.is_valid


def test_duplicate_seller_product_id_reports_error():
    rows = [
        [1, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [1, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert not result.is_valid
    assert any("SellerProductId 1" in e.message for e in result.errors)


def test_new_rows_without_seller_product_id_are_not_duplicates():
    rows = [
        [None, "Товар A", "Группа", "Позиция", 10, "кг", 5, "", ""],
        [None, "Товар B", "Группа", "Позиция", 10, "кг", 5, "", ""],
    ]

    result = BusinessValidator().validate(make_workbook(rows))

    assert result.is_valid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_business_validator.py -v`
Expected: FAIL — `BusinessValidator()` currently requires a `seller_gateway` positional arg, and `.validate()` requires `seller_id`.

- [ ] **Step 3: Rewrite `business_validator.py`**

```python
# backend/app/validation/business_validator.py
from app.parsing.raw_workbook import RawWorkbook
from app.validation.errors import ValidationError, ValidationResult
from app.validation.structure_validator import CATALOG_SHEET

_COL_SELLER_PRODUCT_ID = 0


class BusinessValidator:
    """Проверяет отсутствие дублей SellerProductId внутри каталога.

    PublicationKey больше не проверяется здесь (CR-001,
    docs/06-development/adr/0002-static-google-sheets-template.md) — документ
    Google Sheets не содержит PublicationKey, сверять его с состоянием
    продавца стало нечем.
    """

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        return ValidationResult(errors=self._validate_seller_product_id_uniqueness(workbook))

    def _validate_seller_product_id_uniqueness(self, workbook: RawWorkbook) -> list[ValidationError]:
        catalog = next((sheet for sheet in workbook.sheets if sheet.name == CATALOG_SHEET), None)
        if catalog is None or len(catalog.rows) < 2:
            return []

        rows_by_id: dict[object, list[int]] = {}
        for row_number, row in enumerate(catalog.rows[1:], start=2):
            seller_product_id = row[_COL_SELLER_PRODUCT_ID] if _COL_SELLER_PRODUCT_ID < len(row) else None
            if seller_product_id is None or seller_product_id == "":
                continue
            rows_by_id.setdefault(seller_product_id, []).append(row_number)

        return [
            ValidationError(
                sheet=catalog.name,
                column="SellerProductId",
                message=f"SellerProductId {seller_product_id} дублируется в строках {rows}",
            )
            for seller_product_id, rows in rows_by_id.items()
            if len(rows) > 1
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_business_validator.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/validation/business_validator.py backend/tests/test_business_validator.py
git commit -m "refactor: BusinessValidator drops PublicationKey check and SellerGateway dependency (CR-001)"
```

---

### Task 6: `Validator` — drop `seller_id` parameter

**Files:**
- Modify: `backend/app/validation/validator.py`
- Modify: `backend/tests/test_validator.py`

- [ ] **Step 1: Update the test file first**

In `backend/tests/test_validator.py`:
- `make_validator(session)` now builds `BusinessValidator()` with no args:
  ```python
  def make_validator(session) -> Validator:
      return Validator(
          StructureValidator(),
          SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
          BusinessValidator(),
      )
  ```
- Every `validator.validate(workbook, seller_id=...)` / `make_validator(session).validate(workbook, seller_id)` call drops the `seller_id` argument, e.g.:
  ```python
  def test_valid_workbook_end_to_end_has_no_errors(session):
      row = [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""]
      workbook = make_valid_workbook(row)

      result = make_validator(session).validate(workbook)

      assert result.is_valid
  ```
  ```python
  def test_structure_errors_stop_semantic_and_business_from_running(session):
      workbook = RawWorkbook(source="broken.xlsx", sheets=[])

      validator = Validator(StructureValidator(), _RefusesToRun(), _RefusesToRun())
      result = validator.validate(workbook)

      assert not result.is_valid
  ```
- Remove `insert_seller`/`with_stale_publication_key` and the two tests exercising stale `PublicationKey` behavior at the `Validator` level (`test_combines_semantic_and_business_errors_when_structure_is_valid` currently asserts a stale-key error — that check no longer exists). Replace with a test combining a `SemanticValidator` error and a `BusinessValidator` duplicate-`SellerProductId` error instead, to keep coverage of "both run and combine when structure is valid":
  ```python
  def test_combines_semantic_and_business_errors_when_structure_is_valid(session):
      # Наименование продавца пусто (semantic) + дубль SellerProductId (business)
      rows = [
          [1, "", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", ""],
          [1, "Апельсины оптом", "Цитрусовые", "Апельсин", 50, "кг", 5, "", ""],
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
  Also update `SYSTEM_ROWS` in this file to the new `TemplateVersion`/`TemplateId` pair (same as Task 4):
  ```python
  SYSTEM_ROWS = [
      ["TemplateVersion", "1.0"],
      ["TemplateId", "template-1"],
  ]
  ```
  Drop the now-unused `insert_seller` helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_validator.py -v`
Expected: FAIL — `Validator.validate()` still requires `seller_id` positionally.

- [ ] **Step 3: Update `validator.py`**

```python
# backend/app/validation/validator.py
from app.parsing.raw_workbook import RawWorkbook
from app.validation.business_validator import BusinessValidator
from app.validation.errors import ValidationResult
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator


class Validator:
    """Оркестрирует StructureValidator → SemanticValidator + BusinessValidator.

    Если структура каталога нарушена, построчные проверки не запускаются —
    ошибки про несуществующие колонки были бы шумом поверх уже понятной
    структурной ошибки (см. Publication_Workflow.md: Structure Validation
    предшествует Business Validation, а не выполняется параллельно с ней).
    Semantic и Business при валидной структуре выполняются оба — их ошибки
    собираются в один отчёт, не fail-fast (Publication_Service.md).
    """

    def __init__(
        self,
        structure_validator: StructureValidator,
        semantic_validator: SemanticValidator,
        business_validator: BusinessValidator,
    ):
        self.structure_validator = structure_validator
        self.semantic_validator = semantic_validator
        self.business_validator = business_validator

    def validate(self, workbook: RawWorkbook) -> ValidationResult:
        structure_result = self.structure_validator.validate(workbook)
        if not structure_result.is_valid:
            return structure_result

        errors = []
        errors += self.semantic_validator.validate(workbook).errors
        errors += self.business_validator.validate(workbook).errors
        return ValidationResult(errors=errors)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_validator.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/validation/validator.py backend/tests/test_validator.py
git commit -m "refactor: Validator.validate() drops seller_id — no longer needed (CR-001)"
```

---

### Task 7: `Mapper` / `PublicationMetadata` — new `_System` contract

**Files:**
- Modify: `backend/app/mapping/publication_model.py`
- Modify: `backend/app/mapping/mapper.py:78-88`
- Modify: `backend/tests/test_mapper.py`

- [ ] **Step 1: Update the test file first**

In `backend/tests/test_mapper.py`, replace `SYSTEM_ROWS`:
```python
SYSTEM_ROWS = [
    ["TemplateVersion", "1.0"],
    ["TemplateId", "template-1"],
]
```

Replace `test_maps_system_sheet_and_seller_id_into_metadata`:
```python
def test_maps_system_sheet_and_seller_id_into_metadata():
    workbook = make_workbook([])

    result = Mapper().map(workbook, VALID_RESULT, seller_id=42)

    assert result.metadata.seller_id == 42
    assert result.metadata.template_version == "1.0"
    assert result.metadata.template_id == "template-1"
```

`test_hand_built_fixture_workbook_actually_passes_real_structure_validator` needs its `Товарные группы`/`Товарные позиции` extra sheets unchanged (unaffected); no other test in this file references `PublicationKey`/`CatalogHash`/`DocumentId`/`DocumentVersion`/`GeneratedAt`/`GeneratedBy`, so nothing else changes.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_mapper.py -v`
Expected: FAIL — `PublicationMetadata` doesn't have `template_version`/`template_id` yet; `_map_metadata` doesn't populate them.

- [ ] **Step 3: Update `publication_model.py`**

```python
# backend/app/mapping/publication_model.py
from dataclasses import dataclass


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


@dataclass(frozen=True)
class PublicationMetadata:
    seller_id: int
    template_version: str | None
    template_id: str | None


@dataclass(frozen=True)
class PublicationModel:
    products: list[PublicationProduct]
    metadata: PublicationMetadata
```

- [ ] **Step 4: Update `_map_metadata` in `mapper.py`**

Replace:
```python
    def _map_metadata(self, system: RawSheet, seller_id: int) -> PublicationMetadata:
        values = {row[0]: (row[1] if len(row) > 1 else None) for row in system.rows if row and row[0] in SYSTEM_FIELDS}
        return PublicationMetadata(
            seller_id=seller_id,
            document_id=values.get("DocumentId"),
            document_version=values.get("DocumentVersion"),
            publication_key=values.get("PublicationKey"),
            generated_at=values.get("GeneratedAt"),
            generated_by=values.get("GeneratedBy"),
            catalog_hash=values.get("CatalogHash"),
        )
```
with:
```python
    def _map_metadata(self, system: RawSheet, seller_id: int) -> PublicationMetadata:
        values = {row[0]: (row[1] if len(row) > 1 else None) for row in system.rows if row and row[0] in SYSTEM_FIELDS}
        return PublicationMetadata(
            seller_id=seller_id,
            template_version=values.get("TemplateVersion"),
            template_id=values.get("TemplateId"),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_mapper.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/mapping/publication_model.py backend/app/mapping/mapper.py backend/tests/test_mapper.py
git commit -m "refactor: PublicationMetadata carries template_version/template_id, not document publication data (CR-001)"
```

---

### Task 8: `PublicationService`/`PublicationResult` — explicit `publication_key`/`catalog_hash`, add `publication_id`

**Files:**
- Modify: `backend/app/publication/publication_result.py`
- Modify: `backend/app/publication/publication_service.py`
- Modify: `backend/tests/test_publication_service.py`

- [ ] **Step 1: Update the test file first**

In `backend/tests/test_publication_service.py`:

Replace `make_model` (drops `publication_key`/`catalog_hash` — no longer part of `PublicationModel.metadata`):
```python
def make_model(seller_id: int, products: list[PublicationProduct]) -> PublicationModel:
    return PublicationModel(
        products=products,
        metadata=PublicationMetadata(seller_id=seller_id, template_version="1.0", template_id="template-1"),
    )
```

Update the `PublicationMetadata`/`PublicationModel` import line (unchanged import path, just fewer fields used).

Every call site changes from:
```python
model = make_model(seller_id, [...], publication_key="key-1", catalog_hash="hash-1")
result = service.publish(model, published_by=user_id)
```
to:
```python
model = make_model(seller_id, [...])
result = service.publish(model, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
```

Apply this mechanical change to all 12 test functions in the file (`test_publishes_new_catalog_creates_seller_products`, `test_publishing_again_updates_changed_seller_product`, `test_publishing_alongside_new_product_only_counts_new_one`, `test_publishing_catalog_missing_previous_product_deactivates_it`, `test_conflict_error_rolls_back_all_changes`, `test_seller_product_belonging_to_another_seller_is_rejected`, `test_duplicate_publication_key_is_rejected`, `test_product_returning_after_deactivation_is_reactivated`, `test_product_returning_with_no_other_field_changes_is_still_reactivated`, `test_changing_product_position_resets_moderation_status`, `test_publish_logs_start_and_success`, `test_publish_logs_failure_reason_on_error`, `test_integrity_error_race_on_publication_key_is_wrapped`, `test_identical_catalog_hash_with_fresh_key_short_circuits_without_touching_seller_products`, `test_republishing_the_exact_same_file_is_rejected_as_duplicate`) — move each `publication_key=`/`catalog_hash=` pair from `make_model(...)` to the corresponding `service.publish(...)` call.

Add one new assertion to `test_publishes_new_catalog_creates_seller_products` for the new `publication_id` field:
```python
    assert result.publication_id > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_publication_service.py -v`
Expected: FAIL — `PublicationMetadata()` no longer accepts `publication_key`/`catalog_hash` kwargs; `service.publish()` doesn't accept them either yet.

- [ ] **Step 3: Update `publication_result.py`**

```python
# backend/app/publication/publication_result.py
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationResult:
    success: bool
    publication_id: int
    created_count: int
    updated_count: int
    deactivated_count: int
    publication_key: str
    catalog_hash: str
```

- [ ] **Step 4: Update `publication_service.py`**

Replace the `publish` method signature and body (only the parts touching `publication_key`/`catalog_hash` sourcing and the final `PublicationResult` construction change — the rest of `_apply_catalog`/`_resolve_product_id`/`_has_changed` is untouched):

```python
    def publish(
        self, model: PublicationModel, published_by: int, *, publication_key: str, catalog_hash: str
    ) -> PublicationResult:
        seller_id = model.metadata.seller_id

        logger.info("Публикация начата: seller_id=%s publication_key=%s", seller_id, publication_key)

        try:
            if self.catalog_publication_repository.exists_with_key(publication_key):
                raise DuplicatePublicationError(
                    f"PublicationKey '{publication_key}' уже был использован в предыдущей публикации"
                )

            current_hash = self.seller_gateway.get_current_catalog_hash(seller_id)
            catalog_unchanged = current_hash is not None and catalog_hash == current_hash

            created = updated = deactivated = 0
            if not catalog_unchanged:
                created, updated, deactivated = self._apply_catalog(model.products, seller_id)

            new_version = self.catalog_publication_repository.latest_version(seller_id) + 1
            publication = self.catalog_publication_repository.create(
                seller_id=seller_id,
                version=new_version,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                published_by=published_by,
            )
            self.seller_gateway.update_current_publication(
                seller_id, publication_key=publication_key, catalog_hash=catalog_hash, catalog_version=new_version
            )

            self.session.commit()
            logger.info(
                "Публикация завершена: seller_id=%s publication_key=%s created=%s updated=%s deactivated=%s",
                seller_id, publication_key, created, updated, deactivated,
            )
            return PublicationResult(
                success=True,
                publication_id=publication.id,
                created_count=created,
                updated_count=updated,
                deactivated_count=deactivated,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
            )
        except IntegrityError as exc:
            self.session.rollback()
            logger.warning("Публикация отклонена (гонка PublicationKey): seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise DuplicatePublicationError(f"PublicationKey '{publication_key}' уже используется (конфликт при записи)") from exc
        except Exception as exc:
            self.session.rollback()
            logger.warning("Публикация отклонена: seller_id=%s publication_key=%s error=%s", seller_id, publication_key, exc)
            raise
```

(Everything below `publish` in the file — `_apply_catalog`, `_resolve_product_id`, `_has_changed` — is unchanged; only remove the now-unused `publication_key = model.metadata.publication_key` / `catalog_hash = model.metadata.catalog_hash` local lookups since they're parameters now.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_publication_service.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/publication/publication_result.py backend/app/publication/publication_service.py backend/tests/test_publication_service.py
git commit -m "refactor: PublicationService.publish() takes publication_key/catalog_hash explicitly; PublicationResult gains publication_id (CR-001)"
```

---

### Task 9: Config + dependencies for Google Sheets API

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Add dependencies**

In `backend/pyproject.toml`, add to `dependencies`:
```toml
    "google-api-python-client",
    "google-auth",
    "google-auth-httplib2",
```

Run: `cd backend && uv sync`
Expected: dependencies installed, `uv.lock` updated.

- [ ] **Step 2: Add settings**

In `backend/app/core/config.py`, add two fields:
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    google_service_account_file: str
    google_sheets_timeout_seconds: float = 10.0
```

- [ ] **Step 3: Add `.env.example` entries**

```
GOOGLE_SERVICE_ACCOUNT_FILE=./google-service-account.json
GOOGLE_SHEETS_TIMEOUT_SECONDS=10
```

Also add `google-service-account.json` (or whatever real filename is used) to `backend/.gitignore` if not already covered by a broad `*.json` pattern — check first:

Run: `cd backend && cat .gitignore 2>/dev/null || echo "no .gitignore yet"`

If it doesn't already ignore JSON credential files, append:
```
# Google Service Account credentials — never commit
google-service-account*.json
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/.env.example backend/.gitignore
git commit -m "chore: add Google Sheets API dependencies and Service Account config"
```

---

### Task 10: `GoogleSheetsParser` (new)

**Files:**
- Modify: `backend/app/parsing/exceptions.py`
- Create: `backend/app/parsing/google_sheets_parser.py`
- Test: `backend/tests/test_google_sheets_parser.py`

- [ ] **Step 1: Add new exception types**

```python
# backend/app/parsing/exceptions.py
class ParserError(Exception):
    """Файл источника не удалось прочитать. Общий тип для всех форматов (Excel/CSV/JSON/...),
    чтобы вызывающий код мог ловить одно исключение независимо от формата источника."""


class ExcelParserError(ParserError):
    """Excel-файл повреждён или не является валидным .xlsx."""


class GoogleSheetsParserError(ParserError):
    """Ошибка чтения Google Sheets через Service Account (сеть, таймаут, неожиданный ответ API)."""


class GoogleSheetsNotFoundError(GoogleSheetsParserError):
    """Таблица с указанным spreadsheet_id не существует."""


class GoogleSheetsAccessError(GoogleSheetsParserError):
    """Таблица не расшарена на Service Account GreenMarket."""
```

- [ ] **Step 2: Write the failing test (with a hand-built fake Sheets resource — see plan header "Testing caveat")**

```python
# backend/tests/test_google_sheets_parser.py
import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, GoogleSheetsParserError
from app.parsing.google_sheets_parser import GoogleSheetsParser


class _FakeRequest:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def execute(self, num_retries=0):
        if self._error:
            raise self._error
        return self._payload


class _FakeValues:
    def __init__(self, value_ranges, error=None):
        self._value_ranges = value_ranges
        self._error = error

    def batchGet(self, spreadsheetId, ranges, valueRenderOption):
        assert valueRenderOption == "UNFORMATTED_VALUE"
        return _FakeRequest({"valueRanges": self._value_ranges}, self._error)


class FakeSheetsResource:
    def __init__(self, sheet_titles, rows_by_title=None, get_error=None, values_error=None):
        self._metadata = {"sheets": [{"properties": {"title": t}} for t in sheet_titles]}
        self._get_error = get_error
        rows_by_title = rows_by_title or {}
        self._values = _FakeValues([{"values": rows_by_title.get(t, [])} for t in sheet_titles], values_error)

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId):
        return _FakeRequest(self._metadata, self._get_error)

    def values(self):
        return self._values


def make_http_error(status: int) -> HttpError:
    response = httplib2.Response({"status": status})
    response.status = status
    return HttpError(response, b"{}")


def test_parses_sheets_into_raw_workbook():
    resource = FakeSheetsResource(
        ["Каталог", "_System"],
        rows_by_title={
            "Каталог": [["SellerProductId", "Цена"], [1, 99.5]],
            "_System": [["TemplateVersion", "1.0"]],
        },
    )

    result = GoogleSheetsParser(resource=resource).parse("sheet-id-1")

    assert result.source == "sheet-id-1"
    assert [s.name for s in result.sheets] == ["Каталог", "_System"]
    assert result.sheets[0].rows == [["SellerProductId", "Цена"], [1, 99.5]]


def test_sheet_index_matches_position():
    resource = FakeSheetsResource(["First", "Second"])

    result = GoogleSheetsParser(resource=resource).parse("sheet-id-2")

    assert [(s.name, s.index) for s in result.sheets] == [("First", 0), ("Second", 1)]


def test_not_found_raises_google_sheets_not_found_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(404))

    with pytest.raises(GoogleSheetsNotFoundError):
        GoogleSheetsParser(resource=resource).parse("missing-sheet")


def test_no_access_raises_google_sheets_access_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(403))

    with pytest.raises(GoogleSheetsAccessError):
        GoogleSheetsParser(resource=resource).parse("private-sheet")


def test_other_api_error_raises_generic_parser_error():
    resource = FakeSheetsResource(["Каталог"], get_error=make_http_error(500))

    with pytest.raises(GoogleSheetsParserError):
        GoogleSheetsParser(resource=resource).parse("broken-sheet")


def test_values_batch_get_error_is_wrapped_too():
    resource = FakeSheetsResource(["Каталог"], values_error=make_http_error(403))

    with pytest.raises(GoogleSheetsAccessError):
        GoogleSheetsParser(resource=resource).parse("sheet-id-3")


def test_unexpected_exception_does_not_leak_raw():
    class ExplodingResource(FakeSheetsResource):
        def get(self, spreadsheetId):
            raise RuntimeError("network exploded")

    with pytest.raises(GoogleSheetsParserError):
        GoogleSheetsParser(resource=ExplodingResource(["Каталог"])).parse("sheet-id-4")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_google_sheets_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.parsing.google_sheets_parser'`

- [ ] **Step 4: Write the implementation**

```python
# backend/app/parsing/google_sheets_parser.py
import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, GoogleSheetsParserError
from app.parsing.raw_workbook import RawSheet, RawWorkbook

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class GoogleSheetsParser:
    """Читает Google Sheets в RawWorkbook через Service Account — тот же
    контракт, что ExcelParser (CR-001): не вычисляет PublicationKey/CatalogHash,
    только читает структуру таблицы. `valueRenderOption=UNFORMATTED_VALUE`
    обязателен — иначе числа (цена/остаток) придут строками, что нарушит
    эквивалентность с ExcelParser (openpyxl отдаёт float).

    `resource` — необязательный уже собранный клиент Sheets API (googleapiclient
    resource или тестовый дублёр с тем же интерфейсом `.spreadsheets()`); если не
    передан, строится настоящий клиент из Service Account credentials.
    """

    def __init__(self, resource=None, timeout: float | None = None):
        self.timeout = timeout if timeout is not None else settings.google_sheets_timeout_seconds
        self._service = resource if resource is not None else self._build_service()

    def _build_service(self):
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=_SCOPES
        )
        http = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=self.timeout))
        return build("sheets", "v4", http=http, cache_discovery=False)

    def parse(self, spreadsheet_id: str) -> RawWorkbook:
        try:
            return self._parse(spreadsheet_id)
        except GoogleSheetsParserError:
            raise
        except HttpError as exc:
            raise self._map_http_error(exc, spreadsheet_id) from exc
        except Exception as exc:
            raise GoogleSheetsParserError(f"Ошибка при обращении к Google Sheets API ('{spreadsheet_id}'): {exc}") from exc

    def _parse(self, spreadsheet_id: str) -> RawWorkbook:
        spreadsheets = self._service.spreadsheets()
        metadata = spreadsheets.get(spreadsheetId=spreadsheet_id).execute(num_retries=0)
        sheet_titles = [sheet["properties"]["title"] for sheet in metadata["sheets"]]

        response = spreadsheets.values().batchGet(
            spreadsheetId=spreadsheet_id, ranges=sheet_titles, valueRenderOption="UNFORMATTED_VALUE"
        ).execute(num_retries=0)

        sheets = [
            RawSheet(name=title, index=index, rows=value_range.get("values", []))
            for index, (title, value_range) in enumerate(zip(sheet_titles, response["valueRanges"]))
        ]
        return RawWorkbook(source=spreadsheet_id, sheets=sheets)

    def _map_http_error(self, exc: HttpError, spreadsheet_id: str) -> GoogleSheetsParserError:
        status = exc.resp.status if exc.resp else None
        if status == 404:
            return GoogleSheetsNotFoundError(f"Таблица '{spreadsheet_id}' не найдена")
        if status == 403:
            return GoogleSheetsAccessError(f"Нет доступа к таблице '{spreadsheet_id}' — расшарьте на Service Account")
        return GoogleSheetsParserError(f"Ошибка Google Sheets API при чтении '{spreadsheet_id}': {exc}")
```

Note: `_service.spreadsheets()` in the real `googleapiclient` client is a **method** (returns a resource each call), same as the `FakeSheetsResource` fake above (`spreadsheets()` returns `self`). This matches real client behavior.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_google_sheets_parser.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/parsing/exceptions.py backend/app/parsing/google_sheets_parser.py backend/tests/test_google_sheets_parser.py
git commit -m "feat: add GoogleSheetsParser reading catalog via Service Account (PR-007)"
```

---

### Task 11: `PublicationUseCase` (new)

**Files:**
- Create: `backend/app/application/publication_use_case.py`
- Test: `backend/tests/test_publication_use_case.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_publication_use_case.py
from sqlalchemy import text

from app.application.publication_use_case import PublicationUseCase, PublicationValidationError
from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.publication.errors import DuplicatePublicationError
from tests.test_google_sheets_parser import FakeSheetsResource

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
]
PRODUCT_GROUPS_HEADER = ["ProductGroupId", "ParentProductGroupId", "Наименование"]
PRODUCTS_HEADER = ["ProductId", "ProductGroupId", "Наименование"]
SYSTEM_ROWS = [["TemplateVersion", "1.0"], ["TemplateId", "template-1"]]


def insert_seller(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO Seller (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO User (name) VALUES (:name)"), {"name": name}).lastrowid


def make_resource(catalog_rows: list[list[object]]) -> FakeSheetsResource:
    return FakeSheetsResource(
        ["Каталог", "Товарные группы", "Товарные позиции", "Инструкция", "_System"],
        rows_by_title={
            "Каталог": [CATALOG_HEADER, *catalog_rows],
            "Товарные группы": [PRODUCT_GROUPS_HEADER],
            "Товарные позиции": [PRODUCTS_HEADER],
            "Инструкция": [["текст"]],
            "_System": SYSTEM_ROWS,
        },
    )


def test_publishes_valid_catalog(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма Use Case")
    user_id = insert_user(committing_session, name="Admin")
    resource = make_resource([[None, "Ферма А", "Группа не существует", "Прочее", 50, "кг", 5, "", ""]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    result = use_case.publish("sheet-1", seller_id=seller_id, published_by=user_id)

    assert result.success is True
    assert result.created_count == 1
    assert result.publication_id > 0


def test_validation_error_raises_with_error_list(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма невалидная")
    user_id = insert_user(committing_session, name="Admin")
    # Цена отрицательная — SemanticValidator должен отклонить
    resource = make_resource([[None, "Ферма А", "Группа не существует", "Прочее", -5, "кг", 5, "", ""]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    import pytest
    with pytest.raises(PublicationValidationError) as exc_info:
        use_case.publish("sheet-2", seller_id=seller_id, published_by=user_id)

    assert len(exc_info.value.validation_result.errors) > 0


def test_republishing_same_content_is_idempotent_no_op(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма повтор")
    user_id = insert_user(committing_session, name="Admin")
    resource = make_resource([[None, "Ферма А", "Группа не существует", "Прочее", 50, "кг", 5, "", ""]])
    use_case = PublicationUseCase(committing_session, parser_resource=resource)

    first = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)
    second = use_case.publish("sheet-3", seller_id=seller_id, published_by=user_id)

    assert first.publication_key != second.publication_key  # новый ключ на каждый вызов (CR-001)
    assert (second.created_count, second.updated_count, second.deactivated_count) == (0, 0, 0)
```

Note: `committing_session` fixture is already defined in `backend/tests/conftest.py` (Task requires no changes there).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_publication_use_case.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.publication_use_case'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/application/publication_use_case.py
import uuid

from sqlalchemy.orm import Session

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.mapping.mapper import Mapper
from app.parsing.google_sheets_parser import GoogleSheetsParser
from app.platform.seller_gateway import SellerGateway
from app.publication.hash_calculator import HashCalculator
from app.publication.publication_result import PublicationResult
from app.publication.publication_service import PublicationService
from app.validation.business_validator import BusinessValidator
from app.validation.errors import ValidationResult
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator


class PublicationValidationError(Exception):
    """Каталог не прошёл Structure/Semantic/Business Validation."""

    def __init__(self, validation_result: ValidationResult):
        self.validation_result = validation_result
        super().__init__("Публикация отклонена: ошибки валидации")


class PublicationUseCase:
    """Оркестрирует Publication Pipeline (CR-001, docs/04-services/Publication_Service.md):
    GoogleSheetsParser → HashCalculator → Validator → Mapper → PublicationService.
    PublicationKey/CatalogHash генерируются здесь — не читаются из документа.
    """

    def __init__(self, session: Session, parser_resource=None):
        self.parser = GoogleSheetsParser(resource=parser_resource)
        self.hash_calculator = HashCalculator()
        self.mapper = Mapper()
        self.validator = Validator(
            StructureValidator(),
            SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
            BusinessValidator(),
        )
        self.publication_service = PublicationService(
            session=session,
            seller_gateway=SellerGateway(session),
            seller_product_repository=SellerProductRepository(session),
            product_repository=ProductRepository(session),
            product_group_repository=ProductGroupRepository(session),
            catalog_publication_repository=CatalogPublicationRepository(session),
        )

    def publish(self, spreadsheet_id: str, *, seller_id: int, published_by: int) -> PublicationResult:
        workbook = self.parser.parse(spreadsheet_id)
        catalog_hash = self.hash_calculator.compute(workbook)

        validation_result = self.validator.validate(workbook)
        if not validation_result.is_valid:
            raise PublicationValidationError(validation_result)

        model = self.mapper.map(workbook, validation_result, seller_id)
        publication_key = str(uuid.uuid4())

        return self.publication_service.publish(
            model, published_by, publication_key=publication_key, catalog_hash=catalog_hash
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_publication_use_case.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/application/publication_use_case.py backend/tests/test_publication_use_case.py
git commit -m "feat: add PublicationUseCase orchestrating the Google Sheets publication pipeline (PR-007)"
```

---

### Task 12: REST API — schemas + controller + wiring

**Files:**
- Create: `backend/app/api/v1/schemas.py`
- Create: `backend/app/api/v1/publications.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_publications_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_publications_api.py
from sqlalchemy import text

from app.api.v1.publications import get_google_sheets_parser_resource
from app.main import app
from tests.test_google_sheets_parser import FakeSheetsResource, make_http_error

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
]
PRODUCT_GROUPS_HEADER = ["ProductGroupId", "ParentProductGroupId", "Наименование"]
PRODUCTS_HEADER = ["ProductId", "ProductGroupId", "Наименование"]
SYSTEM_ROWS = [["TemplateVersion", "1.0"], ["TemplateId", "template-1"]]


def insert_seller(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO Seller (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO User (name) VALUES (:name)"), {"name": name}).lastrowid


def make_resource(catalog_rows, **overrides) -> FakeSheetsResource:
    return FakeSheetsResource(
        ["Каталог", "Товарные группы", "Товарные позиции", "Инструкция", "_System"],
        rows_by_title={
            "Каталог": [CATALOG_HEADER, *catalog_rows],
            "Товарные группы": [PRODUCT_GROUPS_HEADER],
            "Товарные позиции": [PRODUCTS_HEADER],
            "Инструкция": [["текст"]],
            "_System": SYSTEM_ROWS,
        },
        **overrides,
    )


def override_session(committing_session):
    from app.infrastructure.database import get_session

    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def override_resource(resource):
    app.dependency_overrides[get_google_sheets_parser_resource] = lambda: resource


def test_successful_publication_returns_200(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма API")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Группа", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-1"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["created"] == 1


def test_missing_sheet_source_returns_422(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма без ссылки")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/publications", json={"seller_id": seller_id, "published_by": user_id})

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validation_errors_return_422_with_details(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ошибка валидации")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Группа", "Прочее", -5, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-2"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert len(response.json()["error"]["details"]) > 0


def test_sheet_not_found_returns_400(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма таблица не найдена")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([], get_error=make_http_error(404)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={"seller_id": seller_id, "published_by": user_id, "spreadsheet_id": "sheet-api-3"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SHEET_NOT_FOUND"


def test_spreadsheet_id_is_extracted_from_sheet_url(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Ферма ссылка")
    user_id = insert_user(committing_session, name="Admin")
    override_session(committing_session)
    override_resource(make_resource([[None, "Ферма А", "Группа", "Прочее", 50, "кг", 5, "", ""]]))
    client = TestClient(app)

    response = client.post(
        "/api/v1/publications",
        json={
            "seller_id": seller_id,
            "published_by": user_id,
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-api-4/edit#gid=0",
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_publications_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.v1.publications'`

- [ ] **Step 3: Write `schemas.py`**

```python
# backend/app/api/v1/schemas.py
import re

from pydantic import BaseModel

_SHEET_URL_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


class PublicationRequest(BaseModel):
    seller_id: int
    published_by: int
    sheet_url: str | None = None
    spreadsheet_id: str | None = None

    def resolve_spreadsheet_id(self) -> str:
        if self.spreadsheet_id:
            return self.spreadsheet_id
        if self.sheet_url:
            match = _SHEET_URL_PATTERN.search(self.sheet_url)
            if match:
                return match.group(1)
        raise ValueError("Не указан sheet_url или spreadsheet_id")


class PublicationResponse(BaseModel):
    success: bool
    publication_id: int
    created: int
    updated: int
    deactivated: int
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[str] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail
```

- [ ] **Step 4: Write `publications.py`**

```python
# backend/app/api/v1/publications.py
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.schemas import ErrorDetail, ErrorResponse, PublicationRequest, PublicationResponse
from app.application.publication_use_case import PublicationUseCase, PublicationValidationError
from app.infrastructure.database import get_session
from app.parsing.exceptions import GoogleSheetsAccessError, GoogleSheetsNotFoundError, ParserError
from app.publication.errors import DuplicatePublicationError, PublicationConflictError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/publications", tags=["publications"])


def get_google_sheets_parser_resource():
    """Переопределяется в тестах (`app.dependency_overrides`) фейковым Sheets-ресурсом —
    см. `backend/tests/test_google_sheets_parser.py::FakeSheetsResource`.
    По умолчанию `None` → PublicationUseCase строит настоящий клиент Google Sheets API."""
    return None


def _error(status_code: int, code: str, message: str, details: list[str] | None = None) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@router.post("", response_model=PublicationResponse)
def create_publication(
    request: PublicationRequest,
    session: Session = Depends(get_session),
    parser_resource=Depends(get_google_sheets_parser_resource),
):
    try:
        spreadsheet_id = request.resolve_spreadsheet_id()
    except ValueError as exc:
        return _error(422, "VALIDATION_ERROR", str(exc))

    logger.info("Публикация начата: seller_id=%s spreadsheet_id=%s", request.seller_id, spreadsheet_id)
    use_case = PublicationUseCase(session, parser_resource=parser_resource)

    try:
        result = use_case.publish(spreadsheet_id, seller_id=request.seller_id, published_by=request.published_by)
    except PublicationValidationError as exc:
        return _error(
            422,
            "VALIDATION_ERROR",
            "Каталог не прошёл валидацию",
            details=[e.message for e in exc.validation_result.errors],
        )
    except DuplicatePublicationError as exc:
        return _error(409, "DUPLICATE_PUBLICATION", str(exc))
    except PublicationConflictError as exc:
        return _error(409, "PUBLICATION_CONFLICT", str(exc))
    except GoogleSheetsNotFoundError as exc:
        return _error(400, "SHEET_NOT_FOUND", str(exc))
    except GoogleSheetsAccessError as exc:
        return _error(400, "SHEET_ACCESS_DENIED", str(exc))
    except ParserError as exc:
        logger.warning("Ошибка Google Sheets API: seller_id=%s error=%s", request.seller_id, exc)
        return _error(500, "GOOGLE_API_ERROR", str(exc))

    logger.info(
        "Публикация завершена: seller_id=%s publication_id=%s created=%s updated=%s deactivated=%s",
        request.seller_id, result.publication_id, result.created_count, result.updated_count, result.deactivated_count,
    )
    return PublicationResponse(
        success=result.success,
        publication_id=result.publication_id,
        created=result.created_count,
        updated=result.updated_count,
        deactivated=result.deactivated_count,
        message="Публикация выполнена успешно",
    )
```

- [ ] **Step 5: Wire the router into `main.py`**

```python
# backend/app/main.py
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.v1.publications import router as publications_router
from app.infrastructure.database import get_session

app = FastAPI(
    title="GreenMarket Backend",
    version="1.0.0",
)
app.include_router(publications_router)


@app.get("/health")
def health(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
    except OperationalError as exc:
        detail = str(exc.orig) if exc.orig else str(exc)
        return {"status": "DOWN", "database": detail}
    return {"status": "UP", "database": "UP"}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_publications_api.py -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas.py backend/app/api/v1/publications.py backend/app/main.py backend/tests/test_publications_api.py
git commit -m "feat: add POST /api/v1/publications REST endpoint (PR-007)"
```

---

### Task 13: Full test suite + `backend/README.md` update

**Files:**
- Modify: `backend/README.md`

- [ ] **Step 1: Run the entire suite to confirm no regressions**

Run: `cd backend && uv run pytest -v`
Expected: all tests pass (previous 83 + new ones from Tasks 3, 10, 11, 12, minus the ~6 removed stale-`PublicationKey`-at-`BusinessValidator`-level tests from Task 5).

- [ ] **Step 2: Update `backend/README.md`**

Add a new top-level section after "Publication Service (PR-006)" documenting the CR-001 rework and the new PR-007 layer, following the file's existing "Отклонения и допущения" convention:

```markdown
## CR-001 — переход на статический шаблон Google Sheets

По итогам согласования с коллегой (три ссылки ChatGPT, зафиксировано ADR
`docs/06-development/adr/0002-static-google-sheets-template.md`) модель
публикации изменена: Google Sheets — статический шаблон, который продавец
копирует сам; GreenMarket никогда не пишет в таблицу. Следствия:

- `_System` больше не хранит `PublicationKey`/`CatalogHash` — только
  `TemplateVersion`/`TemplateId` (метаданные шаблона, не публикации).
- `PublicationKey` (`uuid.uuid4()`) и `CatalogHash` (SHA-256 от содержимого
  листа «Каталог», см. `HashCalculator`) теперь генерируются/вычисляются
  сервером на каждый вызов `POST /api/v1/publications`, а не читаются из
  документа.
- `BusinessValidator` лишился проверки `PublicationKey` (сверять в документе
  больше нечего) и зависимости от `SellerGateway`/`seller_id` — остался
  только дедуп `SellerProductId`.
- `Validator.validate()` лишился параметра `seller_id` — им пользовалась
  только удалённая проверка `PublicationKey`.
- `PublicationMetadata` вместо `document_id`/`document_version`/
  `publication_key`/`generated_at`/`generated_by`/`catalog_hash` содержит
  `template_version`/`template_id`.
- `PublicationService.publish()` принимает `publication_key`/`catalog_hash`
  именованными параметрами (генерируются новым `PublicationUseCase`, не
  читаются из `PublicationModel.metadata`). `PublicationResult` получил
  `publication_id` (id созданной записи `CatalogPublication`) — нужен для
  REST-ответа.

**Открытый вопрос коллеге** (тот же паттерн, что и незакрытый вопрос
`CatalogHash`-алгоритма из PR-004): точная область хеширования
`CatalogHash` не была указана в CR-001 буквально — реализовано как SHA-256
от JSON-сериализации строк данных листа «Каталог» (без заголовка, с учётом
порядка строк), в `HashCalculator`. Если коллега имел в виду другой охват
(например, включая `_System`/справочники) — потребуется отдельное
согласование, так как это меняет CatalogHash для уже опубликованных
каталогов.

## Google Sheets Parser + Publication REST API (PR-007)

`GoogleSheetsParser.parse(spreadsheet_id) -> RawWorkbook` — тот же контракт,
что `ExcelParser`, читает таблицу через Service Account
(`spreadsheets.values.batchGet`, `valueRenderOption=UNFORMATTED_VALUE` —
обязательно, иначе числа придут строками). Таймаут — 10 секунд (настраивается
`GOOGLE_SHEETS_TIMEOUT_SECONDS`), retry не реализован (Stage 1, синхронная
публикация — лучше быстрый отказ, чем зависший запрос).

`PublicationUseCase.publish(spreadsheet_id, seller_id, published_by)` —
оркестрирует весь пайплайн: `GoogleSheetsParser → HashCalculator (до
Validator, CR-001) → Validator → Mapper → PublicationService`, генерирует
`PublicationKey`.

`POST /api/v1/publications` (`backend/app/api/v1/publications.py`) —
JSON-тело `{seller_id, published_by, sheet_url | spreadsheet_id}`. Ошибки
преобразуются в единый формат `docs/04-services/REST_API.md`
(`{"error": {"code","message","details"}}`): `422` — ошибки валидации
каталога или отсутствие `sheet_url`/`spreadsheet_id`; `400` —
`SHEET_NOT_FOUND`/`SHEET_ACCESS_DENIED`; `409` —
`DUPLICATE_PUBLICATION`/`PUBLICATION_CONFLICT`; `500` — прочие ошибки
Google API.

**Тестирование `GoogleSheetsParser` — отклонение от принципа «без mock».**
Все остальные интеграционные тесты проекта бьют в реальную MySQL, без mock.
Google Sheets API не может быть вызван офлайн, а полноценный интеграционный
тест (как просит коллега) требует реальный тестовый Google Sheet,
расшаренный на Service Account — инфраструктура, которую нужно завести
отдельно (см. `GOOGLE_SERVICE_ACCOUNT_FILE` в `.env.example`). Пока это не
готово, `GoogleSheetsParser` и вся цепочка выше него (`PublicationUseCase`,
REST-контроллер) тестируются через инъекцию `resource`/`parser_resource` —
самодельный дублёр `FakeSheetsResource` (`tests/test_google_sheets_parser.py`),
не библиотека мокирования. Когда появится реальный Service Account и
тестовая таблица — добавить отдельный `test_google_sheets_parser_integration.py`
по образцу `test_product_repository.py` (реальная сеть, реальная таблица).
```

- [ ] **Step 3: Commit**

```bash
git add backend/README.md
git commit -m "docs: document CR-001 rework and PR-007 (GoogleSheetsParser + REST API) in backend/README.md"
```

---

## Self-Review

**Spec coverage:**
- CR-001 items 1–7 (ADR text) → Tasks 1, 4, 5, 6, 7, 8. ✅
- PR-007 spec: `POST /api/v1/publications`, JSON body (`sheet_url`/`spreadsheet_id`), Controller/UseCase/Service layering, `PublicationResponse` fields, HTTP codes, error envelope, logging → Tasks 11, 12. ✅
- Colleague's 4 accepted technical decisions (UNFORMATTED_VALUE, trailing cells no-op, Service Account env/ADR, 10s timeout/no retry) → Task 9 (config), Task 10 (`GoogleSheetsParser`). ✅
- Doc updates required "в составе PR-007" → Task 2. ✅
- Not-in-scope items from original spec (queue, async, publication history, republish, OAuth, sheet auto-creation, write-back) — correctly absent from this plan; no task attempts them. ✅

**Placeholder scan:** No `TODO`/`TBD` in any step; every code step is complete, runnable code; every test has real assertions, not "assert True" stubs.

**Type consistency:** `PublicationMetadata(seller_id, template_version, template_id)` used identically in Tasks 7, 8, 11 fixtures. `PublicationService.publish(model, published_by, *, publication_key, catalog_hash) -> PublicationResult` (with `publication_id`) used identically in Tasks 8, 11, 12. `GoogleSheetsParser(resource=..., timeout=...)` constructor matches across Tasks 10, 11 (`parser_resource` param name in `PublicationUseCase.__init__` forwards to `GoogleSheetsParser(resource=parser_resource)` — verified consistent). `FakeSheetsResource`/`make_http_error` defined once in Task 10's test file and imported by Tasks 11/12's tests (`from tests.test_google_sheets_parser import ...`) rather than duplicated.

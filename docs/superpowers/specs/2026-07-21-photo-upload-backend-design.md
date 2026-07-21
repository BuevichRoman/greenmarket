# Design: Photo Upload Backend (цикл 1 из 3 — карточка товара продавца)

**Дата:** 2026-07-21
**Статус:** Approved (Roman), design для внутренней реализации — не отправляется коллеге на отдельное согласование (реализует уже согласованное с ним архитектурное решение по CR-001, см. `kwork/tasks.md`/[[greenmarket-crud-card-photo-upload-deferred]]).

## Контекст

19–20.07 коллега разрешил два конфликта вокруг фичи «карточка товара + фото»: карточка — это редактор строки внутри Google Sheets продавца (Apps Script), а CR-001 («GreenMarket никогда не пишет в таблицу») сохраняется без исключений — платформа не пишет ни в саму таблицу, ни фото-URL в неё. Фича была сознательно отложена и оставлена в приоритетном бэклоге.

Разведка при старте реализации показала, что задача решается в 3 независимых, но последовательных цикла (backend/шаблон → Apps Script → Customer UI), потому что Apps Script и Customer UI оба зависят от готового backend-контракта. Настоящий документ — только цикл 1.

**Находка при разведке:** хранилище фото уже полностью спроектировано и задеплоено на проде — `Photo` (миграция 004: `id`, `s3_key`) и `SellerProductPhoto` (миграция 006: `seller_product_id`, `photo_id`, `sort_order` — уже many-to-many с порядком, т.е. схема готова к нескольким фото на товар). `PhotoGateway`/`CatalogUseCase` уже читают эти таблицы и отдают `photos: [s3_key, ...]` в Catalog API (`GET /catalog/products`, `GET /catalog/products/{id}`); `buyer-web` уже имеет `PhotoPlaceholder`/`ProductCard`, ожидающие реальных данных. Разрыв — только в том, что ничего никогда не писало в `Photo`/`SellerProductPhoto`: нет колонки «Фото» в Catalog Template, Parser/Validator/Mapper её не знают, Publication Service её не синхронизирует, и нет endpoint'а для загрузки файла. Это меняет расклад по сравнению с первоначальным предположением «фото пока одно» — раз схема БД уже это умеет, цикл 1 сразу поддерживает несколько фото на товар.

## Scope

**В объём:**
- Новый REST endpoint `POST /api/v1/photos` — загрузка файла в S3, создание `Photo`.
- Новая обязательная колонка «Фото» в листе «Каталог» (список `Photo.id` через `;`), новая `TemplateVersion`.
- `StructureValidator`/`SemanticValidator`/`Mapper` — поддержка новой колонки.
- `PublicationService` — синхронизация `SellerProductPhoto` при публикации.
- Пересборка `catalog_template_v1.xlsx` под новую версию, обновление `Catalog_Template.md`/`Seller_Workspace.md`.

**Вне объёма (сознательно, отдельные циклы):**
- Apps Script (карточка-сайдбар, вызов `POST /api/v1/photos`, запись `photo_id` в ячейку) — цикл 2.
- Любые изменения `buyer-web`/Customer UI — цикл 3; по разведке выше там, вероятно, почти нечего делать (уже принимает `photos[]`), но проверка/полировка — отдельный заход.
- Поддержка старой `TemplateVersion` (без фото) — реальных продавцов ещё нет (единственный тестовый на проде правится вручную), держать два пайплайна ради него не нужно.
- Жёсткая проверка принадлежности `photo_id` загрузившему продавцу — `Photo.seller_id` добавляется только для трассируемости (см. ниже), не как enforced constraint в этом цикле.
- Ограничения на размер/формат файла свыше базовых (см. «Endpoint» ниже) — без экзотики (антивирус, резайз, CDN) до появления реальной нагрузки.

## Backend

### Миграция `database/migrations/010_alter_photo_add_seller.sql`

```sql
ALTER TABLE Photo
    ADD COLUMN seller_id BIGINT UNSIGNED NULL
        COMMENT 'Продавец, загрузивший фото (трассируемость; не enforced ownership check — см. design doc цикла 1)',
    ADD INDEX idx_Photo_seller (seller_id);
```

Nullable и без FK на `Seller` (платформенная таблица вне схемы GreenMarket, тот же паттерн, что `SellerProduct.seller_id`/`CatalogPublication.seller_id` — сырой `INTEGER`, не FK, см. `SellerGateway`).

`backend/app/infrastructure/models.py`: добавить `seller_id: Mapped[int | None]` в `Photo`. `Photo` сейчас не смаплен как ORM-модель (`PhotoGateway` читает её сырым SQL) — модель нужно завести, т.к. `POST /api/v1/photos` создаёт запись через ORM (см. «Repository» ниже); `PhotoGateway` остаётся как есть (read-only sql, не трогаем).

### Repository

Новый `PhotoRepository` (`backend/app/infrastructure/repositories/photo_repository.py`):

```python
class PhotoRepository:
    def create(self, *, s3_key: str, seller_id: int) -> Photo: ...
    def exists_all(self, photo_ids: list[int]) -> bool:
        """Для SemanticValidator — все ли id существуют одним запросом."""
```

Новый `SellerProductPhotoRepository` (`backend/app/infrastructure/repositories/seller_product_photo_repository.py`):

```python
class SellerProductPhotoRepository:
    def replace_for_product(self, seller_product_id: int, photo_ids: list[int]) -> None:
        """Удаляет все существующие строки под seller_product_id, вставляет
        заново с sort_order = позиция в списке. Полная замена, не diff —
        проще и достаточно (порядок фото на товар редко меняется построчно,
        весь список приходит одной публикацией)."""
```

### S3-клиент

В проекте пока нет ни одного клиента для записи в S3 (`PhotoGateway` только читает `s3_key` из БД, сам файл никогда не трогает). Нужен новый `app/platform/photo_storage.py`:

```python
class PhotoStorage:
    def __init__(self, bucket: str, ...):  # boto3, конфиг из settings (аналогично SELLER_ACCESS_TOKENS — новые переменные в .env, не в git)
        ...
    def upload(self, file_bytes: bytes, content_type: str) -> str:
        """Генерирует уникальный ключ (uuid4 + расширение по content_type),
        кладёт в bucket, возвращает s3_key."""
```

`boto3` добавляется в зависимости backend (`pyproject.toml`).

### Endpoint `POST /api/v1/photos`

Новый файл `app/api/v1/photos.py`, роутер `prefix="/api/v1"`.

- **Запрос:** `multipart/form-data`, поля `access_token` (str) + `file` (upload).
- **Авторизация:** `resolve_seller_access(access_token)` — тот же механизм, что `POST /publications` (401, если токен невалиден).
- **Валидация файла:** `content_type` из allowlist (`image/jpeg`, `image/png`, `image/webp`), ограничение размера (например 10 МБ) — `413`/`422` при нарушении. Без резайза/сжатия в этом цикле.
- **Успех:** `201`, тело `{"photo_id": int}`.
- **Логика:** `PhotoStorage.upload()` → `PhotoRepository.create(s3_key=..., seller_id=access.seller_id)` → commit → вернуть `photo_id`.

Endpoint полностью независим от Publication Pipeline — просто создаёт `Photo`, ни на что не ссылается. Связь с товаром появляется только при следующей публикации (через колонку «Фото» и `SellerProductPhoto`).

### `structure_validator.py`

```python
CATALOG_COLUMNS = [
    ...,
    _Column("Дополнительные характеристики", required=False),
    _Column("Фото", required=True),  # новая
]

SUPPORTED_TEMPLATE_VERSIONS = {"2.0"}  # было {"1.0"}; старая версия не поддерживается (см. Scope)
```

`backend/app/catalog_template/data.py`: `TEMPLATE_VERSION = "2.0"` (было `"1.0"`) — записывается в лист `_System` при генерации шаблона, должно совпадать с `SUPPORTED_TEMPLATE_VERSIONS` выше.

### `semantic_validator.py`

Новая проверка на уровне строки: ячейка «Фото» → split по `;`, trim, каждый элемент — `int`; список не пуст (обязательное поле — та же ошибка `_required_field_empty`, если пусто); каждый `photo_id` существует в `Photo` (`PhotoRepository.exists_all`, один SQL-запрос на всю строку/весь каталог — не N+1, аналогично `product_group_repository.find_by_name` для группы, но батчево). Формат ошибки — как у остальных полей (`ValidationError(sheet, row, column="Фото", message=...)`).

### `mapper.py`

`PublicationProduct.photo_ids: list[int]` (новое поле, `mapping/publication_model.py`). `_map_row`: `_COL_PHOTOS = _COLUMN_INDEX["Фото"]`, парсинг `"12;15;7"` → `[12, 15, 7]` (порядок сохраняется — это будущий `sort_order`).

### `publication_service.py`

`_apply_catalog`:
- В обеих ветках (create/update) после upsert `SellerProduct` вызывать `seller_product_photo_repository.replace_for_product(seller_product.id, item.photo_ids)`.
- `_has_changed()` — добавить сравнение `photo_ids` (иначе публикация с той же ценой/остатком, но новым фото, не попадёт в ветку обновления и фото не синхронизируются). Нужно сравнивать со списком `photo_id` из текущих `SellerProductPhoto` строк (упорядоченным по `sort_order`) — небольшая доп. выборка в начале `_apply_catalog` (аналогично `existing_by_id`), не отдельный запрос на строку.

### Пересборка нормативного артефакта

Изменение `CATALOG_COLUMNS`/`TEMPLATE_VERSION`/`SUPPORTED_TEMPLATE_VERSIONS` — по существующей процедуре «Процесс выпуска новой версии шаблона» (`Catalog_Template.md`): обновить `backend/app/catalog_template/data.py`, пересобрать `catalog_template_v1.xlsx` и `templates/examples/*.xlsx` (`build.py`/`build_examples.py`), закоммитить.

## Документация

- `Catalog_Template.md` — новая колонка «Фото» в разделе «Структура рабочего каталога», обновить `TemplateVersion` во всех упоминаниях.
- `Seller_Workspace.md` — раздел 4 (без изменений состава листов, но комментарий колонки «Каталог»), раздел 12 (версионирование — фиксация новой версии), раздел 10 (UX — колонка «Фото» защищена от ручного редактирования продавцом так же, как `SellerProductId`, т.к. пишется только Apps Script в цикле 2; в этом цикле физической защиты диапазона ещё нет, т.к. шаблон не знает про Apps Script — зафиксировать как TODO цикла 2).
- `REST_API.md` — добавить `POST /api/v1/photos` в раздел Publication API (или новый раздел «Photo API» — решить при реализации по аналогии с существующим стилем документа).

## Тестирование

- `PhotoStorage` — юнит-тест с моком S3-клиента (загрузка, генерация ключа, ошибка сети → проброс исключения).
- `POST /api/v1/photos` — интеграционный тест: валидный токен + файл → `201` + `photo_id`; невалидный токен → `401`; неподдерживаемый `content_type` → `422`; файл сверх лимита → `413`.
- `StructureValidator`/`SemanticValidator`/`Mapper` — тесты по образцу существующих (`test_mapper.py`, тесты валидаторов): новая колонка присутствует/отсутствует/пуста/содержит несуществующий id/несколько id.
- `PublicationService._apply_catalog` — тест синхронизации `SellerProductPhoto` при create/update/повторной публикации с тем же набором фото (не должно пересоздавать без надобности — либо намеренно принять, что `replace_for_product` всегда делает DELETE+INSERT, это ок при малом числе фото на товар).
- Пересобранные `templates/examples/*.xlsx` — прогнать через `test_catalog_template_artifact.py` (полный pipeline).

## Открытые вопросы для цикла 2 (не блокируют цикл 1)

- Формат Apps Script UI (сайдбар vs модальное окно) — решить при бренсторме цикла 2.
- Как Apps Script обрабатывает удаление/переупорядочивание фото в карточке (нужно ли доп. API кроме upload, например `DELETE /api/v1/photos/{id}`) — не входит в цикл 1, т.к. `SellerProductPhoto.replace_for_product` на бэкенде уже принимает любой список при публикации; вопрос только в UX самого Apps Script.

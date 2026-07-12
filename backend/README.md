# GreenMarket Backend

PR-001 — Bootstrap. PR-002 — Database Infrastructure. PR-003 — Parser.
PR-004 — Validator. PR-005 — Mapper. PR-006 — Publication Service (первый
слой, реально пишущий в БД). Matcher/REST API — следующие PR.

## MySQL

Нужна MySQL 8.0.16+ с уже применённой схемой из `../database/migrations/001-006`
(+ платформенные таблицы Seller/User/Photo — на реальном окружении это
iBronevik, локально — см. `docs/03-database/Physical_Model.md` про их состав).
Пример через Docker:

```bash
docker run -d --name greenmarket-mysql \
  -e MYSQL_ROOT_PASSWORD=<пароль> -p 3307:3306 mysql:8.0.36
```

Затем применить по порядку: стаб платформенных таблиц (Seller/User/Photo,
только для dev/CI, не часть продукта, см. `tests/fixtures/platform_stub.sql`)
→ `../database/migrations/00{1..6}_*.sql` → `../database/seeders/00{1,2}_*.sql`.

## Переменные окружения

```bash
cp .env.example .env
```

`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — см. `.env.example`.
Заполнить реальными значениями своего MySQL (порт из примера выше — `3307`).

## Запуск Backend

```bash
uv sync
uv run uvicorn app.main:app --reload
```

```
GET /health
{"status": "UP", "database": "UP"}
```

Если MySQL недоступна — `{"status": "DOWN", "database": "<текст ошибки>"}`,
HTTP 200 (как в присланном ТЗ; отдельный код ответа, например 503, для
неисправного состояния не запрашивался — можно добавить отдельным PR, если
понадобится реальным потребителям `/health`, например системе мониторинга).

## Тесты

```bash
uv run pytest
```

`tests/test_product_repository.py` — интеграционный тест на реальной БД (без
mock, как в ТЗ PR-002): ищет товар по имени (без захардкоженных id, см. правку
сидера в `kwork/timeline.md`, п.29), затем проверяет `find_by_id()`. Требует
поднятую и наполненную БД (см. выше). В CI это делает
`.github/workflows/backend-ci.yml` перед прогоном тестов.

`tests/test_seller_gateway.py`/`test_business_validator.py`/`test_validator.py`
(частично) — тоже на реальной БД: вставляют тестовую строку `Seller` внутри
той же сессии без `commit()`, читают её обратно через `SellerGateway`; фикстура
`session` (см. `tests/conftest.py`) закрывает сессию без коммита в `finally` —
транзакция откатывается сама, БД не засоряется тестовыми продавцами.

`tests/test_publication_service.py` — `PublicationService` первым в проекте
реально обязан коммитить/откатывать транзакцию, поэтому фикстура `session`
(рассчитанная на «никогда не коммитить») не годится. Используется отдельная
фикстура `committing_session`: соединение + внешняя транзакция + `Session(bind=
connection, join_transaction_mode="create_savepoint")` (SQLAlchemy 2.0) —
`commit()`/`rollback()` внутри теста и внутри самого `PublicationService`
работают на уровне SAVEPOINT, а внешняя транзакция откатывается целиком в
`finally` фикстуры. Проверено отдельно (3 прогона подряд): БД после каждого —
0 строк в `Seller`/`SellerProduct`/`CatalogPublication`.

## Структура

```
backend/
├── app/
│   ├── api/v1/        — REST-контроллеры (пусто, PR-008)
│   ├── application/    — сценарии использования (пусто, PR-007)
│   ├── domain/         — доменная модель (пусто, PR-006/007)
│   ├── infrastructure/
│   │   ├── database.py    — engine, SessionLocal, Base, get_session()
│   │   ├── models.py      — ORM-модели существующих таблиц (Database First)
│   │   └── repositories/  — явные репозитории (без GenericRepository):
│   │       ProductRepository, ProductGroupRepository (PR-002),
│   │       SellerProductRepository, CatalogPublicationRepository (PR-006)
│   ├── parsing/         — чтение источников каталога в RawWorkbook (PR-003)
│   │   ├── raw_workbook.py  — RawWorkbook/RawSheet (внутреннее представление)
│   │   ├── exceptions.py    — ParserError, ExcelParserError
│   │   └── excel_parser.py  — ExcelParser: .xlsx → RawWorkbook
│   ├── validation/      — проверка RawWorkbook против правил GreenMarket (PR-004)
│   │   ├── errors.py             — ValidationError, ValidationResult
│   │   ├── structure_validator.py — обязательные листы/колонки/версия шаблона
│   │   ├── semantic_validator.py  — значения строк «Каталог» (нужны репозитории PR-002)
│   │   ├── business_validator.py  — PublicationKey, дедуп SellerProductId
│   │   └── validator.py           — оркестратор Structure → Semantic + Business
│   ├── platform/        — Anti-Corruption Layer к платформенным данным (PR-004/006)
│   │   └── seller_gateway.py — SellerGateway: читает и обновляет Seller напрямую (не ORM)
│   ├── mapping/         — RawWorkbook → PublicationModel (PR-005)
│   │   ├── errors.py             — MapperError
│   │   ├── publication_model.py  — PublicationModel/PublicationProduct/PublicationMetadata
│   │   └── mapper.py             — Mapper: чистое преобразование структуры, без бизнес-логики
│   ├── publication/     — PublicationModel → БД (PR-006)
│   │   ├── errors.py              — PublicationError/DuplicatePublicationError/PublicationConflictError
│   │   ├── publication_result.py  — PublicationResult
│   │   └── publication_service.py — PublicationService: атомарная публикация каталога продавца
│   ├── core/           — конфигурация приложения
│   └── main.py
└── tests/
```

## Parser (PR-003)

`ExcelParser.parse(path) -> RawWorkbook` читает `.xlsx` в внутреннее представление
(`RawWorkbook.source` + список `RawSheet(name, index, rows)`). Parser не знает
ничего о правилах GreenMarket — не проверяет обязательные листы/колонки/версию
шаблона (это `Validator`, PR-004), не типизирует и не валидирует значения ячеек
(`Semantic`/`Business Validation`, тоже PR-004). Он только читает данные как есть.

**Принципы (см. `kwork/timeline.md`, п.37 — согласовано с коллегой):**

- **Детерминированность.** Один и тот же файл → всегда один и тот же
  `RawWorkbook`. Formulas читаются `data_only=False` (сырая формула-строка, не
  закэшированное значение — оно зависит от того, когда файл в последний раз
  пересчитывался в Excel).
- **Ничего не терять.** Пустые строки/колонки, скрытые листы, значения
  смёрженных ячеек (кроме top-left — по семантике `.xlsx` только он несёт
  значение) — Parser их не отбрасывает и не домысливает, решение об
  интерпретации принимают более поздние слои.
- **Единый тип ошибки.** Любая ошибка чтения (битый файл, не `.xlsx`) → одно
  исключение `ExcelParserError` (наследник общего `ParserError`) — вызывающий
  код (`Publication Service`) сможет ловить `ParserError`, не зная формат
  источника, когда появятся `CSVParser`/`JSONParser`.

## Validator (PR-004)

`Validator.validate(workbook, seller_id) -> ValidationResult` проверяет
`RawWorkbook` (из PR-003) против правил GreenMarket в три уровня (см.
`kwork/timeline.md`, п.37 — согласовано с коллегой):

- **`StructureValidator`** — форма документа против контракта **Excel
  Template v1.0** (согласован с коллегой, `kwork/timeline.md`, п.38):
  обязательные листы, точные заголовки и порядок колонок листов «Каталог» /
  «Товарные группы» / «Товарные позиции», обязательные поля `_System`,
  поддерживаемая версия шаблона (`DocumentVersion`). Лист «Инструкция» —
  свободный текст, структура не проверяется.
- **`SemanticValidator`** — построчные значения листа «Каталог»: обязательные
  поля не пусты, `Цена`/`Остаток` — неотрицательные числа, `Товарная группа
  GreenMarket` существует в справочнике, `Товарная позиция GreenMarket`
  существует **в пределах уже найденной группы** (через
  `ProductGroupRepository`/`ProductRepository` из PR-002 — `UNIQUE(name)` на
  `Product` сознательно не используется, идентификация в БД выполняется
  комбинацией ProductGroup + Product, см. `database/migrations/002_create_products.sql`;
  `Прочее` — разрешённое значение позиции, не требует существования в `Product`).
- **`BusinessValidator`** — актуальность и непустота `PublicationKey` (через
  `SellerGateway`) и отсутствие дублей `SellerProductId` внутри каталога.

`Validator` (оркестратор): если `StructureValidator` вернул ошибки —
`SemanticValidator`/`BusinessValidator` не запускаются (ошибки по
несуществующим колонкам были бы шумом). Если структура валидна — оба
запускаются, ошибки собираются в один список, **не fail-fast**
(`Publication_Service.md`: «Ошибки собираются в единый отчёт»).

**`SellerGateway`** (`app/platform/`) — Anti-Corruption Layer к `Seller`
(предложено коллегой, `kwork/timeline.md`, п.38): `Seller` намеренно не
смаплен как ORM-модель (GreenMarket им не владеет, см. `models.py`), поэтому
`get_current_publication_key(seller_id)`/`get_current_catalog_hash(seller_id)`
читают его напрямую (`session.execute(text(...))`). Если источник платформенных
данных сменится (REST/gRPC API вместо прямого доступа к БД), меняется только
этот файл — `Validator` не знает, откуда пришли данные.

## Mapper (PR-005)

`Mapper.map(workbook, validation_result, seller_id) -> PublicationModel`
превращает уже провалидированный `RawWorkbook` во внутреннюю доменную модель
`PublicationModel`, независимую одновременно от Excel (`openpyxl`) и от
SQLAlchemy/ORM (задание коллеги, `kwork/timeline.md`, п.41). Pipeline:
`Parser → RawWorkbook → Validator → Mapper → PublicationModel → Publication
Service`.

Mapper не принимает бизнес-решений — не обращается к `Repository`,
`SellerGateway`, не ищет `Product`/`ProductGroup`, не пишет в БД. Все проверки
уже выполнены `Validator`; если `ValidationResult` содержит ошибки, Mapper
выбрасывает `MapperError` вместо преобразования — по контракту он вообще не
должен вызываться в этом случае, обращение к нему при невалидном документе
считается ошибкой вызывающего кода (Programming Error), а не пользовательской
ошибкой.

`PublicationProduct` содержит ровно те поля, что перечислены в задании:
`seller_product_id`, `seller_name`, `product_group_name`, `product_name`,
`price`, `unit`, `stock`, `description`, `attributes` — построчно из листа
«Каталог» (те же 9 колонок, что и `CATALOG_COLUMNS` в `structure_validator.py`,
переиспользуется только порядок, без повторной проверки значений).

## Publication Service (PR-006)

`PublicationService.publish(model, published_by) -> PublicationResult` — первый
слой пайплайна, реально изменяющий состояние БД (задание коллеги,
`kwork/timeline.md`, п.46). Транзакционно применяет уже промапленную
`PublicationModel` к каталогу продавца:

- **Проверка `PublicationKey`** — через `CatalogPublicationRepository.exists_with_key()`:
  если этот ключ уже встречался в истории публикаций (`UNIQUE INDEX
  uk_CatalogPublication_key`, миграция 005) — `DuplicatePublicationError`
  (защита от повторной обработки уже опубликованного документа). Это не
  повтор проверки `BusinessValidator` (PR-004, «ключ совпадает с текущим»
  у продавца) — другая проверка, другой смысл (см. «Отклонения» ниже).
- **Проверка `CatalogHash`** — если совпадает с текущим `Seller.current_catalog_hash`,
  `SellerProduct` не трогается (0 create/update/deactivate), но версия/лог
  публикаций и `current_publication_key` у продавца всё равно обновляются.
- **`SellerProduct`**: без `SellerProductId` — создаётся новый; с
  `SellerProductId` — обновляется существующий после проверки принадлежности
  текущему `seller_id` (иначе `PublicationConflictError`, тот же код для
  случая, когда такого `SellerProductId` вообще нет). Изменившимся считается
  товар при изменении цены/остатка/описания/группы/позиции/единицы/имени
  продавца **или если товар был деактивирован и теперь снова присутствует в
  каталоге** — в этом случае `is_published` возвращается в `True` даже если
  остальные поля не менялись (без этого условия реактивация не сработала бы
  для товара, вернувшегося без единой правки). Пропавшие из публикации
  товары не удаляются — переводятся в `is_published = False`, история
  сохраняется.
- **Смена товарной позиции** (`product_id` меняется на другое значение,
  включая `None ↔ реальный Product`) трактуется как новая заявка на
  классификацию (`docs/02-domain/Catalog_Template.md`, «Изменение товарной
  позиции GreenMarket»): `moderation_status` сбрасывается в `WAIT_PRODUCT`,
  `moderator_id`/`moderated_at`/`moderation_comment` очищаются — предыдущее
  решение модератора относилось к другой позиции. Срабатывает только когда
  `product_id` реально меняется, не на каждое обновление товара.
- **Journal**: каждая публикация — новая строка `CatalogPublication`
  (`version` = предыдущий + 1 для этого продавца), `Seller.current_publication_key`/
  `current_catalog_hash`/`current_catalog_version` обновляются через
  `SellerGateway.update_current_publication()` (та же ACL, что и чтение).
- **Транзакция**: любая ошибка (`PublicationConflictError`,
  `DuplicatePublicationError` или любая другая) — `session.rollback()` и
  проброс исключения; успешный путь — один `session.commit()` в конце.
  `IntegrityError` от гонки на `UNIQUE(publication_key)` (два `publish()` с
  одним ключом одновременно — окно между `exists_with_key()` и собственным
  `INSERT`) перехватывается отдельно и переупаковывается в
  `DuplicatePublicationError`, чтобы наружу не утекала чужая (SQLAlchemy)
  ошибка в нарушение контракта «только собственные ошибки».
- **Логирование**: начало публикации, `seller_id`, `publication_key` — на
  старте; при успехе — те же поля плюс счётчики created/updated/deactivated;
  при любой ошибке — `seller_id`/`publication_key`/причина, уровень warning.

## CR-001 — переход на статический шаблон Google Sheets

По итогам согласования с коллегой (три ссылки ChatGPT, зафиксировано ADR
`docs/06-development/adr/0002-static-google-sheets-template.md`) модель
публикации изменена: Google Sheets — статический шаблон, который продавец
копирует сам; GreenMarket никогда не пишет в таблицу. Следствия:

- `_System` больше не хранит `PublicationKey`/`CatalogHash` — только
  `TemplateVersion`/`TemplateId` (метаданные шаблона, не публикации).
- `PublicationKey` (`uuid.uuid4()`) и `CatalogHash` (SHA-256 от содержимого
  листа «Каталог», вычисляется `HashCalculator` ДО Validator) теперь
  генерируются/вычисляются сервером на каждый вызов `POST /api/v1/publications`,
  а не читаются из документа.
- `BusinessValidator` лишился проверки `PublicationKey` (сверять в документе
  больше нечего) и зависимости от `SellerGateway`/`seller_id` — остался
  только дедуп `SellerProductId`.
- `Validator.validate()` лишился параметра `seller_id` — им пользовалась
  только удалённая проверка `PublicationKey`.
- `PublicationMetadata` вместо `document_id`/`document_version`/
  `publication_key`/`generated_at`/`generated_by`/`catalog_hash` содержит
  `template_version`/`template_id`.
- `PublicationService.publish()` принимает `publication_key`/`catalog_hash`
  явленными параметрами (генерируются новым `PublicationUseCase`, не
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
Validator, CR-001) → Validator (без seller_id, CR-001) → Mapper →
PublicationService`, генерирует `PublicationKey`.

`POST /api/v1/publications` (`backend/app/api/v1/publications.py`) —
JSON-тело `{seller_id, published_by, sheet_url | spreadsheet_id}`. HTTP-коды:
- `200` — успешная публикация
- `422` — `VALIDATION_ERROR` (отсутствие `sheet_url`/`spreadsheet_id`, ошибки
  валидации каталога, ошибки парсинга JSON-тела)
- `403` — `SHEET_ACCESS_DENIED` (`GoogleSheetsAccessError`: Service Account
  без доступа к таблице)
- `404` — `SHEET_NOT_FOUND` (`GoogleSheetsNotFoundError`: неправильный ID)
- `409` — `DUPLICATE_PUBLICATION` (публикация с этим `PublicationKey` уже
  была обработана) или `PUBLICATION_CONFLICT` (конфликт при обновлении
  `SellerProduct`)
- `500` — `GOOGLE_API_ERROR` (внутренние ошибки Google API, сообщение
  обобщённое, сырой exception не отправляется клиенту) или `INTERNAL_ERROR`
  (любая другая неожиданная ошибка, например неудача при загрузке Service
  Account credentials — deliberate last-resort catch-all, гарантирует что
  клиент всегда получит `{"error": {...}}` вместо дефолтной FastAPI ошибки).

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

## Отклонения и допущения CR-001

- **Алгоритм хеширования `CatalogHash`.** CR-001 не специфицирует буквально
  какие именно данные хешируются — реализовано как SHA-256 от JSON листа
  «Каталог», см. `HashCalculator` в `app/publication/`. Если коллега имел в
  виду другой охват (например, с включением служебных данных или справочников)
  — потребуется отдельное согласование и миграция уже опубликованных каталогов.

## Найдено и исправлено независимым архитектурным ревью PR-007

Дополнительный раунд review (после первого мёрджа кода с основным функционалом)
обнаружил и подтвердил необходимость 5 качественных фиксов:

- **(a) `PublicationUseCase` конструировалась вне try/except** — загрузка
  Service Account credentials (если некорректна) выбрасывала бы ошибку до
  вхождения в try-блок, и клиент получал бы дефолтный FastAPI ответ вместо
  project-specific `{"error": {...}}` конверта. Исправлено: конструирование
  `PublicationUseCase` перенесено в начало try-блока; добавлен generic
  `Exception` catch-all с `INTERNAL_ERROR` кодом.
- **(b) Pydantic's собственные ошибки валидации JSON-тела** (например
  неправильный тип поля) использовали дефолтный FastAPI формат
  `{"detail": [...]}` вместо project-specific конверта. Исправлено: добавлен
  global `RequestValidationError` обработчик в `app/main.py`, преобразует
  ошибки Pydantic в `422`/`VALIDATION_ERROR`.
- **(c) HTTP-коды для Google Sheets ошибок** изначально оба маппились на
  `400`, что не соответствует семантике уже определённой в
  `docs/04-services/REST_API.md`. Исправлено: `GoogleSheetsAccessError` →
  `403`/`SHEET_ACCESS_DENIED`, `GoogleSheetsNotFoundError` → `404`/
  `SHEET_NOT_FOUND`.
- **(d) Generic `ParserError` в 500-ветке** изначально отправлял клиенту
  сырой текст исключения, нарушая принцип изоляции (утечка внутренних
  деталей реализации). Исправлено: fixed generic message, сам exception
  логируется server-side на `warning`.
- **(e) Покрытие error-путей** — тесты для 403, 404, 500/INTERNAL_ERROR и
  400-ветки `RequestValidationError` не были предусмотрены в базовом
  функционале. Добавлены.

## Найдено при реализации PR-006: ORM не знает про DB-side DEFAULT

`SellerProduct`/`CatalogPublication` (Database First, `models.py`) не
объявляют `server_default` для колонок с MySQL-side `DEFAULT`/`ON UPDATE
CURRENT_TIMESTAMP` (`is_published`, `moderation_status`, `created_at`,
`updated_at`, `published_at`) — первая в проекте запись через ORM
(`SellerProductRepository`/`CatalogPublicationRepository`, все предыдущие PR
только читали) сразу же упала на `NOT NULL` constraint: SQLAlchemy шлёт explicit
`NULL` для несписанных атрибутов, а не опускает колонку из INSERT, поэтому
DB-side `DEFAULT` не применяется. Исправлено передачей этих полей явно в
момент создания записи (`is_published=True`, `moderation_status="WAIT_PRODUCT"`,
`created_at`/`updated_at`/`published_at` = текущее время), без изменения
`models.py`. Актуально для будущих PR, пишущих в эти таблицы (Matcher/REST
API) — тот же нюанс встретится там же.

## Найдено и исправлено независимым архитектурным ревью PR-005

Тот же процесс, что и для PR-003/PR-004 (`kwork/timeline.md`, п.39): два
независимых агента-ревьюера (не знавших, кто автор кода), каждый нашёл и
подтвердил личным воспроизведением до фикса:

- **Строка, нарушающая контракт «Workbook уже провалидирован», роняла Mapper
  сырым `TypeError`/`ValueError` вместо `MapperError`** — задание прямо
  требует «Mapper может выбрасывать только MapperError». `_map_row` теперь
  оборачивает преобразование в `try/except (TypeError, ValueError)` и
  перевыбрасывает `MapperError` с номером строки.
- **Текстовые поля (`seller_name`, `unit`, `product_group_name`,
  `product_name`, `description`, `attributes`) не приводились к `str`** —
  `SemanticValidator` проверяет `seller_name`/`unit` только на непустоту
  (`if not value`), поэтому число вроде `777` в ячейке проходит валидацию, но
  до фикса Mapper пропускал его как `int`, хотя тип поля объявлен `str`.
  Теперь явно приводится через `str()`/`_to_str_or_none()`.
- **Индексы колонок каталога были третьей независимой копией** порядка,
  уже зафиксированного в `CATALOG_COLUMNS` (`structure_validator.py`) и
  повторённого в `semantic_validator.py`. Теперь `_COL_*` выводятся из
  `CATALOG_COLUMNS` по имени колонки — драфт шаблона больше не может
  разойтись с Mapper молча.
- **Тест на отсутствие зависимости от SQLAlchemy/БД/Gateway был поиском
  подстроки по исходному тексту** — не поймал бы, например, `from
  app.infrastructure.models import SellerProduct` (прямой импорт ORM-сущности,
  не содержащий ни одного из запрещённых слов). Переписан через `ast`-разбор
  реальных `import`/`from … import …` модуля — проверяет фактический граф
  импортов, а не текст.
- **Не было тестов на оба defensive-пути `_find_sheet`** (отсутствующий лист
  «Каталог»/`_System`), **на нормализацию `"" → None`** и **на согласованность
  тестовой фикстуры с реальным `StructureValidator`** — добавлены все три.

## Найдено и исправлено независимым архитектурным ревью PR-003/PR-004

Два независимых агента-ревьюера (не знавших, кто автор кода) нашли и коллега
подтвердил как обязательные до мёрджа (см. `kwork/timeline.md`, п.39) — все
воспроизведены лично перед фиксом, не приняты на веру:

- **PR-003:** лист-диаграмма (`chartsheet`, у него нет ячеек) ронял `ExcelParser`
  сырым `AttributeError` вместо `ExcelParserError` — try/except оборачивал
  только `load_workbook`, не чтение листов. Исправлено: chartsheet
  представляется как `RawSheet` с пустыми `rows` (ему нечего терять — только
  сам график), и вся операция чтения (не только открытие файла) теперь под
  одним try/except.
- **PR-004:** пустое (но присутствующее) значение поля `PublicationKey` в
  `_System` проходило `StructureValidator` (проверялось только наличие поля,
  не значения) и тихо пропускалось в `BusinessValidator` — полностью обходя
  защиту от устаревшей/скомпрометированной копии каталога
  (`Catalog_Template.md`, «Защита служебных данных»). Исправлено на обоих
  уровнях: `StructureValidator` теперь требует непустое значение для каждого
  служебного поля, `BusinessValidator` тоже больше не пропускает проверку при
  пустом/отсутствующем ключе (полезно, если он используется отдельно от
  оркестратора).
- **PR-004:** `IndexError` при `_System`-листе с полностью пустой колонкой
  значений (`row[1]` без проверки длины строки) — Validator падал вместо
  возврата `ValidationResult` с ошибками на невалидном входе. Исправлено в
  `StructureValidator` и `BusinessValidator`.
- **PR-004:** `SemanticValidator` искал `Product` по имени глобально, хотя
  `database/migrations/002_create_products.sql` прямо фиксирует: `UNIQUE(name)`
  сознательно не используется, идентификация — по комбинации ProductGroup +
  Product. Исправлено: товар теперь ищется через `list_by_group()` уже
  найденной группы, не глобальным `find_by_name()`.

## Отклонения и допущения PR-004

- **Проверка целостности `CatalogHash` не реализована.** `Catalog_Template.md`
  требует проверять «целостность документа (CatalogHash)», миграция
  `005_create_catalog_publications.sql` фиксирует алгоритм как SHA-256, но
  область хеширования (какие именно байты/поля документа хешируются,
  исключая сам `CatalogHash`, чтобы не было циклической зависимости) нигде не
  специфицирована. Реализовывать это без согласования с коллегой рискованно —
  будущий генератор документа в Publication Service должен считать хеш
  идентичным образом, иначе валидный документ будет отклоняться. Оставлено
  как открытый вопрос для следующего согласования.
- **Проверка ссылок на фотографии не реализована.** `Publication_Service.md`
  упоминает «ссылки на фотографии» как часть валидации данных, но
  утверждённый Excel Template v1.0 (`kwork/timeline.md`, п.38) не содержит
  колонки для фото в листе «Каталог» — фотографии, по всей видимости,
  загружаются отдельным механизмом вне этого шаблона. Добавлять проверку
  несуществующей колонки было бы домыслом.
- **`SemanticValidator`/`BusinessValidator`/`Validator` не производят типизированное
  представление для будущего Mapper (PR-005)** — только `ValidationResult`
  (список ошибок). Design PR-005 ещё не согласован; заранее придумывать его
  входной контракт было бы преждевременно (YAGNI) — при необходимости Mapper
  сможет сам привести значения к нужному виду, опираясь на уже проверенный
  `RawWorkbook`.
- **`seller_id` передаётся в `Validator`/`BusinessValidator` явным параметром**,
  не читается из `_System` — в согласованном контракте `_System` нет поля с
  идентификатором продавца (там только `DocumentId`/`DocumentVersion`/
  `PublicationKey`/`GeneratedAt`/`GeneratedBy`/`CatalogHash`). Это и корректнее
  с точки зрения безопасности: `Catalog_Template.md` прямо требует не
  доверять служебным данным файла без проверки — идентификатор продавца
  должен приходить из аутентифицированного контекста запроса (будущий
  Publication Service), а не из содержимого файла.
- **Точный заголовок листа «Каталог» проверяется для всех 9 колонок в фиксированном
  порядке, включая необязательные** (`SellerProductId`, `Товарная позиция
  GreenMarket`, `Описание`, `Дополнительные характеристики`) — «необязательность»
  из Excel Template v1.0 трактуется как допустимость пустого *значения* в
  строке данных, а не как разрешение опускать саму колонку из заголовка
  (иначे порядок колонок терял бы смысл для необязательной колонки в середине
  списка, например «Товарная позиция GreenMarket» перед «Цена»). Если коллега
  имел в виду не это — нужно уточнить отдельно.
- **`_System` читается как список пар (поле, значение) по первым двум ячейкам
  каждой строки** — точный построчный формат этого листа коллега не прислал
  (только список полей), это разумное дефолтное предположение для
  key-value-листа, не проверенное отдельно.

## Отклонения и допущения PR-006

Задание (`kwork/timeline.md`, п.46) не описывает буквально несколько мест —
решения ниже нужно согласовать с коллегой, как и открытые вопросы PR-004/005:

- **Смысл проверки `PublicationKey`.** Формулировка задания допускает два
  прочтения. Выбрано: `PublicationKey` проверяется на существование в
  истории публикаций (`CatalogPublication.publication_key`, `UNIQUE INDEX
  uk_CatalogPublication_key`) — если уже встречался, значит документ уже был
  обработан (replay), публикация отклоняется. Это отдельная, более поздняя
  (транзакционная) проверка, чем «ключ совпадает с текущим у продавца» —
  её уже делает `BusinessValidator` (PR-004) до вызова Mapper/Publication
  Service; Publication Service её не повторяет.
- **Полное совпадение `CatalogHash` не означает «вообще ничего не делать»**:
  `SellerProduct` не трогается (0 изменений — прямое требование задания «не
  выполнять UPDATE»), но новая строка `CatalogPublication` всё равно
  создаётся — этим новый `PublicationKey` «сжигается» в истории
  (`exists_with_key()`), иначе при повторной подаче именно этого файла
  (тот же ключ и тот же хеш) replay-защита не сработала бы. *Уточнение
  после независимого ревью:* `Seller.current_publication_key` на этом пути
  фактически не меняет значения — `BusinessValidator` (PR-004) уже
  гарантирует, что ключ документа равен текущему до вызова Publication
  Service, так что запись того же значения обратно — безвредный no-op, не
  критичная для безопасности «ротация». Первоначальная формулировка здесь
  («иначе старый ключ остался бы текущим навсегда») была неточной — это
  найдено независимым ревью.
- **«Неактивен» (пропавший из публикации товар) маппится на
  `SellerProduct.is_published = False`** — отдельного enum/статуса для этого
  в схеме (миграция 003) нет.
- **`SellerProductId`, отсутствующий среди товаров продавца вообще** (не
  просто принадлежащий другому продавцу), тоже считается
  `PublicationConflictError` — не создаётся новая запись с этим ID вручную
  (PK автоинкрементный, ID должен быть выдан сервером ранее).
- **`published_by` — явный параметр `publish()`, не из содержимого файла** —
  тот же принцип, что и `seller_id` в Validator/Mapper (PR-004/005, см. ниже):
  идентификатор доверенного контекста не читается из документа.
- **«Дополнительные характеристики» (`attributes`) нигде не сохраняются.**
  `Mapper` их извлекает (PR-005), но у `SellerProduct` (миграция 003) нет
  такой колонки — сравнивать/сохранять нечем. Не добавлял колонку без ADR;
  открытый вопрос коллеге, как незакрытые вопросы `CatalogHash`-алгоритма
  (PR-004) и `Decimal` vs `float` (PR-005).
- **Разрешение `product_group_name`/`product_name` в `product_id`**
  переиспользует `ProductGroupRepository`/`ProductRepository` — Publication
  Service доверяет, что группа/позиция существуют (уже проверено
  `SemanticValidator`), не перепроверяет их отдельно.

## Найдено и исправлено независимым архитектурным ревью PR-006

Тот же процесс, что и для PR-003/004/005 (`kwork/timeline.md`, п.39/43): два
независимых агента-ревьюера (Opus, чистый контекст, без знания авторства),
каждый нашёл и лично воспроизвёл на реальной MySQL до фикса:

- **Деактивированный товар нельзя было вернуть в публикацию.** `_apply_catalog`
  реализовывал только одно направление инварианта («пропал из каталога ⇒
  `is_published=False`») — для существующей записи в ветке обновления
  `is_published` не трогалось вообще. Товар, однажды пропавший из каталога и
  вернувшийся позже по тому же `SellerProductId` (в том числе без единой
  правки полей), оставался невидимым навсегда — прямое нарушение
  идемпотентности «republish того же контента ⇒ то же состояние БД» из
  задания. Исправлено: `existing.is_published = True` при любом обновлении
  существующей записи, плюс `_has_changed()` учитывает `not
  existing.is_published` как самостоятельное условие изменения (иначе
  реактивация без сопутствующей правки других полей не срабатывала бы).
- **Смена товарной позиции не сбрасывала `moderation_status`.**
  `docs/02-domain/Catalog_Template.md` («Изменение товарной позиции
  GreenMarket») прямо требует: смена `product_id` — новая заявка на
  классификацию, `moderation_status → WAIT_PRODUCT`,
  `moderator_id`/`moderated_at`/`moderation_comment` очищаются. Код это не
  делал — решение модератора могло молча остаться привязанным к уже другой
  позиции. Исправлено точечно: сброс происходит только когда `product_id`
  реально меняется, не на каждое обновление записи.
- **Логирование отсутствовало.** Задание явно перечисляет обязательные точки
  лога (старт, `seller_id`, `publication_key`, счётчики, успех/причина
  ошибки) — в коде не было ни одного вызова. Добавлено через стандартный
  `logging` на старте/успехе/ошибке публикации.
- **`IntegrityError` от гонки на `UNIQUE(publication_key)` мог утечь наружу
  как чужое (SQLAlchemy) исключение**, нарушая контракт «Publication Service
  возвращает только собственные ошибки». Воспроизведено тестом, симулирующим
  окно гонки (репозиторий, у которого `exists_with_key()` намеренно не видит
  уже существующий ключ, а реальный `UNIQUE INDEX` на `CatalogPublication`
  всё равно есть). Исправлено: `IntegrityError` перехватывается отдельно и
  переупаковывается в `DuplicatePublicationError`.
- **Слабое название теста и пробел в покрытии** — `test_identical_catalog_hash_is_idempotent_no_op`
  переименован в `test_identical_catalog_hash_with_fresh_key_short_circuits_without_touching_seller_products`
  (он проверял short-circuit по хешу с НОВЫМ ключом, а не идемпотентность
  повторной публикации одного и того же файла). Добавлен отдельный
  `test_republishing_the_exact_same_file_is_rejected_as_duplicate` — буквально
  обязательный по ТЗ кейс «re-publish the exact same file» (тот же
  `PublicationKey` И тот же `CatalogHash`), которого не было.
- **Уточнение формулировки** (не баг, но неверное обоснование) — см. пункт
  про `CatalogHash` выше: причина обновления журнала на hash-match ветке —
  не «иначе ключ навсегда останется текущим» (это неверно: `BusinessValidator`
  уже гарантирует совпадение до вызова PS), а «сжечь ключ в истории
  `CatalogPublication` на случай буквального повтора того же файла».

Оба агента сошлись Request Changes с одинаковым основным дефектом
(реактивация) — совпадение, аналогичное PR-003/004/005. Полный прогон после
фиксов: 83/83 теста зелёные (было 76: +2 на реактивацию/модерацию, +1 на
`IntegrityError`, +2 на логирование, +1 на буквальный повтор файла, +1
переименован без изменения смысла — итог заменил прежний тест на два).

## Отклонения и допущения PR-005

- **Точный состав `PublicationMetadata` не был прислан коллегой** — задание
  описывает `PublicationModel` как `products` + `metadata` без списка полей
  metadata (в отличие от `PublicationProduct`, где список полей дан явно).
  Собрана из тех же полей `_System`, что уже проверяет `StructureValidator`
  (`DocumentId`/`DocumentVersion`/`PublicationKey`/`GeneratedAt`/`GeneratedBy`/
  `CatalogHash`) плюс `seller_id` явным параметром (тот же принцип, что и в
  `Validator` — идентификатор продавца не читается из файла, см. «Отклонения
  и допущения PR-004»). Разумное дефолтное предположение, не проверенное
  отдельно с коллегой.
- **`Mapper` выбрасывает `MapperError`, если вызван с невалидным
  `ValidationResult`**, хотя задание описывает это как ответственность
  вызывающего кода («Mapper вообще не вызывается»). Добавлена одна защитная
  проверка на входе — соответствует букве задания («Mapper может выбрасывать
  только `MapperError` при внутренних нарушениях контракта»), сам факт вызова
  с невалидным результатом и есть такое нарушение.
- **`price`/`stock` приводятся к `float`** — `SemanticValidator` уже
  гарантирует, что это `int`/`float` (не `bool`), но сырое значение из ячейки
  Excel может быть любым из двух; единое представление типа — часть
  ответственности Mapper («приводит данные к единому представлению»).
- **Пустая строка (`""`) в необязательных текстовых полях
  (`seller_product_id`, `product_name`, `description`, `attributes`)
  нормализуется в `None`** — тоже часть «нормализации структуры данных»,
  явно разрешённой заданием.
- **`price`/`stock` остаются `float`, не `Decimal`.** Найдено независимым
  ревью (см. ниже): openpyxl отдаёт IEEE `float`, и задание не называет тип
  явно, но будущая ORM-модель, скорее всего, будет использовать `NUMERIC`.
  Решение оставлено открытым для согласования с коллегой — конвертация в
  `Decimal` на границе Mapper тривиальна, если понадобится, но домысливать
  точность денежного типа без задания рискованно.
- **Плейсхолдер `"Прочее"` (разрешённое значение «Товарная позиция
  GreenMarket» без записи в `Product`, см. `SemanticValidator`) проходит через
  Mapper как обычная строка `product_name="Прочее"`**, без специальной
  интерпретации — знание о том, что это плейсхолдер, а не название конкретного
  товара, намеренно не добавлено в Mapper (это уже предметная логика,
  запрещённая заданием). Publication Service должен будет знать про это
  значение при обработке.

## Отклонения от присланного ТЗ PR-003

- **Excel-комментарии (`cell.comment`) и форматирование ячеек не захватываются**
  в `RawWorkbook`, хотя коллега предлагал ничего не терять вплоть до
  комментариев. `docs/02-domain/Catalog_Template.md` не описывает комментарии
  как часть модели рабочего каталога — добавление их сейчас раздувает
  представление без обоснованной необходимости на Stage 1 (Keep MVP Small,
  Simplicity Before Flexibility). Если понадобится — отдельное решение
  отдельным PR.
- **`CsvParserError`/`JsonParserError` не заведены** — коллега предлагал сразу
  расширить иерархию исключений под будущие форматы; этих парсеров ещё нет,
  заводить исключения под них преждевременно.

## Отклонения от исходной спецификации PR-001

- **Нет вложенной `backend/database/`.** Миграции и seed-данные уже существуют
  в `../database/migrations/` и `../database/seeders/` на уровне корня
  репозитория (see `docs/03-database/Database_Migrations.md`) — дублировать их
  здесь означало бы два источника истины для одной и той же схемы.
- **Нет `alembic` в зависимостях.** Договорённость по стеку (см.
  `kwork/timeline.md`, п.30) явно фиксирует Database First и независимость SQL
  от ORM — миграции пишутся вручную по `docs/03-database/DDL_Specification.md`,
  а не генерируются из SQLAlchemy-моделей. Добавление Alembic сейчас создало бы
  соблазн смешать эти два подхода. Если появится реальная причина использовать
  Alembic только как раннер (без autogenerate), это отдельное решение будущего PR.

## Найден и исправлен баг (при реализации PR-002)

`app/core/config.py` из присланной спецификации PR-001 не читал `.env` —
`pydantic_settings.BaseSettings` без явного `model_config = SettingsConfigDict(env_file=".env")`
берёт только настоящие переменные окружения ОС. В PR-001 это было незаметно:
`config.py` существовал, но никем не импортировался. В PR-002 `database.py`
впервые реально использует `settings` — ошибка сразу проявилась при первом
запуске тестов. Добавлена одна строка (`env_file=".env"` в `model_config`).

## Отклонения от присланного ТЗ PR-002

- **Реализованы только `ProductRepository` и `ProductGroupRepository`.**
  ТЗ называет ещё `SellerProductRepository` и `CatalogPublicationRepository`
  как пример желаемого паттерна (взамен `GenericRepository`), но явно требует
  только "первый Repository" и "первый интеграционный тест" как критерий
  приёмки. Добавлять непроверенные репозитории для веток, которые ещё не
  используются, — преждевременно; паттерн (явные репозитории без generic-обёртки)
  уже виден на двух реализованных примерах.

# GreenMarket Backend

PR-001 — Bootstrap. PR-002 — Database Infrastructure. PR-003 — Parser.
PR-004 — Validator. Без бизнес-логики (Publication Service/Matcher/REST API —
следующие PR).

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
│   │   └── repositories/  — явные репозитории (без GenericRepository)
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
│   ├── platform/        — Anti-Corruption Layer к платформенным данным (PR-004)
│   │   └── seller_gateway.py — SellerGateway: читает Seller напрямую (не ORM)
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
  GreenMarket`/`Товарная позиция GreenMarket` существуют в справочниках
  (через `ProductGroupRepository`/`ProductRepository` из PR-002; `Прочее` —
  разрешённое значение позиции, не требует существования в `Product`).
- **`BusinessValidator`** — актуальность `PublicationKey` (через
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

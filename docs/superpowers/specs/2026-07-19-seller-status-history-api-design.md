# Design: Seller API (статус + история публикаций) + экраны 1/5 Seller Cabinet

**Дата:** 2026-07-19
**Статус:** Approved (Roman), design для внутренней реализации — не отправляется коллеге на отдельное согласование, т.к. реализует уже утверждённые им `REST_API.md` (Seller API, `GET /api/v1/publications`) и `Seller_MVP.md` (Экраны 1 и 5).

## Контекст

Из пяти экранов `Seller_MVP.md` реализованы только Экран 3 (Публикация) и Экран 4 (Ошибки) — оба против `POST /api/v1/publications`. Экраны 1 (Главная — статус продавца) и 5 (История публикаций) не реализованы, потому что backing API для них (Seller API из `REST_API.md`: `GET /api/v1/seller/catalog`, `GET /api/v1/publications`) не написан вообще — 0% кода.

Отдельно от colleague-инициированного вопроса про CRUD-кнопки/фото (тот вопрос сейчас на паузе, ждёт ответа коллеги — см. `kwork/tasks.md`/`timeline.md` за 19.07) — этот design закрывает то, что не зависит от внешнего решения: доделать уже согласованный REST API и подключить его к уже существующим экранам Seller Cabinet.

## Находка при разведке: история публикаций не может показать обязательное поле без миграции

`Seller_MVP.md`, Экран 5, требует «количество обработанных товаров» в истории. Но `CatalogPublication` (миграция 007) хранит только `version`/`publication_key`/`catalog_hash`/`published_at`/`published_by` — счётчики `created`/`updated`/`deactivated` существуют только в одноразовом `PublicationResult` (`backend/app/publication/publication_result.py`), возвращаются в HTTP-ответе `POST /publications` и нигде не сохраняются. Без миграции этот пункт Экрана 5 нереализуем.

Решение: аддитивная миграция, добавляющая 3 колонки. Не нарушает append-only принцип `CatalogPublication` (миграция 007, «Архитектурные решения» №8 — по-прежнему только `INSERT`, просто с бо́льшим количеством полей).

## Scope

**В объём:**
- Миграция 009: `CatalogPublication` + `created_count`/`updated_count`/`deactivated_count`.
- `GET /api/v1/seller/catalog?access_token=...` — статус-сводка продавца (не полный список товаров).
- `GET /api/v1/publications?access_token=...` — история публикаций, только прод-БД (`aristotel_taxi`).
- Seller Cabinet: простая навигация на 4 экрана (Главная / История / Публикация / Ошибки), Экран 1 и Экран 5 подключены к новым эндпоинтам.
- Точечная правка `REST_API.md`: тело `POST /publications` (устарело — описывает `seller_id/published_by`, реально `access_token`) и уточнение формы ответа `GET /seller/catalog`.

**Вне объёма (сознательно):**
- Тест/прод-переключатель для Экранов 1/5 — сейчас показываем только прод (`aristotel_taxi`). Если понадобится смотреть тестовую историю в кабинете — отдельный заход, не блокирует текущий.
- CRUD-карточка товара, загрузка фото — отдельный вопрос, ждёт ответа коллеги (конфликтует с уже утверждённым принципом «без ручного редактирования», см. `Seller_Workspace.md` §14, `Seller_MVP.md` «Ограничения»).
- Экран 2 «Рабочий каталог» — уже отмечен в `Seller_MVP.md` как устаревший (описывает скачивание Excel, архитектура ушла на Google Sheets по CR-001), в этот заход не трогаем.
- Реальные `id_user` продавцов — блокер на коллеге, не наша часть.
- JS-тесты для фронтендов — в проекте нет тестовой инфраструктуры на JS-стороне (Buyer Web/Seller Cabinet верифицировались вручную в браузере), не вводим её здесь без отдельного запроса.

## Backend

### Миграция `database/migrations/009_alter_catalog_publications_add_counts.sql`

```sql
ALTER TABLE CatalogPublication
    ADD COLUMN created_count     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Создано SellerProduct при этой публикации',
    ADD COLUMN updated_count     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Обновлено SellerProduct при этой публикации',
    ADD COLUMN deactivated_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Деактивировано SellerProduct при этой публикации';
```

`backend/app/infrastructure/models.py`: те же 3 поля добавляются в ORM-модель `CatalogPublication`.

Тесты, требующие синхронизации со схемой (по опыту прошлой миграции 003→008, см. [[greenmarket-stage1-pipeline-live]]): `tests/fixtures/` (если там фигурирует `CatalogPublication`), `backend-ci.yml` (глоб миграций расширить до 009), локальный Docker `greenmarket-mysql`.

### Repository/Service изменения

- `CatalogPublicationRepository.create()` — новые параметры `created_count`, `updated_count`, `deactivated_count`, пишутся в новые колонки.
- `CatalogPublicationRepository.list_by_seller(seller_id) -> list[CatalogPublication]` — новый метод, `ORDER BY version DESC`.
- `SellerProductRepository.count_published(seller_id) -> int` — новый метод (`COUNT(*) WHERE seller_id=... AND is_published=True`).
- `SellerGateway.get_status(seller_id) -> SellerStatus | None` — новый метод, тот же паттерн сырого SQL к платформенной таблице `Seller`, что и остальные методы гейтвея; dataclass `SellerStatus(is_active: bool, current_catalog_version: int)`.
- `PublicationService.publish()` — передаёт `created`/`updated`/`deactivated` в `repository.create()` (уже вычисляются, просто не передавались раньше).

### API

**`GET /api/v1/seller/catalog?access_token=...`** (новый файл `app/api/v1/seller.py`, роутер `prefix="/api/v1/seller"`, по образцу `catalog.py`)

Резолвит `access_token` через уже существующий `resolve_seller_access` (тот же 403 `SELLER_ACCESS_DENIED`, что у `POST /publications`). Ответ:

```json
{
  "seller_id": 1669,
  "is_active": true,
  "current_catalog_version": 3,
  "published_product_count": 12,
  "last_published_at": "2026-07-19T14:32:00Z"
}
```

Если у продавца ещё не было ни одной публикации — `current_catalog_version: 0`, `last_published_at: null`, `published_product_count: 0`. Если `SellerGateway.get_status` не находит строку `Seller` вообще (некорректно настроенный токен — `SELLER_ACCESS_TOKENS` указывает на несуществующий `seller_id`) — `404 SELLER_NOT_FOUND`, не `403` (токен валиден, проблема в конфигурации, а не в доступе).

**`GET /api/v1/publications?access_token=...`** (добавляется в существующий `app/api/v1/publications.py`, тот же роутер `prefix="/api/v1/publications"`)

```json
{
  "publications": [
    {"version": 3, "published_at": "2026-07-19T14:32:00Z", "created": 2, "updated": 1, "deactivated": 0}
  ]
}
```

Пустой продавец → `{"publications": []}`.

### Документация

`REST_API.md`:
- Раздел Publication API: тело `POST /api/v1/publications` меняется с `{"seller_id", "published_by", "sheet_url"}` на `{"access_token", "sheet_url"}` (либо `spreadsheet_id`) — синхронизация с уже задеплоенным поведением.
- Раздел Seller API: `GET /api/v1/seller/catalog` — уточнение, что это статус-сводка, а не построчный список товаров (в системе пока нигде не нужен построчный список конкретно по этому эндпоинту — у покупателя свой Catalog API, у продавца источник истины — сама Google-таблица).

## Frontend (Seller Cabinet)

Простой стейт-навигатор (`useState`, без роутера — тот же минимализм, что в Buyer Web/текущем Seller Cabinet, оба без router-библиотеки). Верхний нав-бар: Главная / История / Публикация. Точка входа по умолчанию не меняется — экран «Публикация» (чтобы не трогать уже проверенный сценарий). «Ошибки» не в нав-баре — показывается как результат неуспешной публикации, как сейчас.

- `api.ts`: `fetchSellerStatus(token)`, `fetchPublicationHistory(token)`.
- `HomeScreen.tsx` — статус/версия/дата/счётчик; если `is_active=false` — уведомление «Ожидает активации» (текст по `Seller_MVP.md`, раздел «Статус продавца»).
- `HistoryScreen.tsx` — таблица публикаций (версия / дата / created / updated / deactivated), пустое состояние — «Публикаций ещё не было».

## Тестирование

Backend — TDD, интеграционные тесты на реальной MySQL, без моков (`committing_session`, как в `test_publication_service.py`): repository-тесты (запись/чтение счётчиков, `list_by_seller` порядок), `SellerGateway.get_status` (активный/неактивный/несуществующий продавец), оба API-эндпоинта (200 с реальными данными, 403 по невалидному токену, пустая история для нового продавца). Frontend — верификация в браузере (Claude_Browser preview), тем же способом, что Buyer Web/Seller Cabinet раньше.

## Definition of Done

- Миграция 009 применена локально и синхронизирована с CI/тестовыми фикстурами.
- `GET /api/v1/seller/catalog` и `GET /api/v1/publications` реализованы, покрыты интеграционными тестами, весь набор тестов зелёный.
- `REST_API.md` синхронизирован с реальным поведением.
- Seller Cabinet показывает все 4 экрана, проверено вручную в браузере на реальных demo-продавцах (1669/1670/1671) с реальной историей публикаций.

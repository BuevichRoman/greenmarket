# GreenMarket REST API

**Version:** 1.0
**Status:** Normative

## Назначение

Настоящий документ определяет публичный REST API GreenMarket Stage 1. REST API является единственной точкой взаимодействия пользовательских интерфейсов с серверной частью системы. Прямой доступ UI к базе данных запрещён.

## Общие принципы

REST API строится на следующих принципах:

- Stateless;
- JSON;
- HTTPS;
- UTF-8;
- Versioned API;
- Resource-oriented.

## Версионирование

Все запросы используют префикс `/api/v1/`. Изменение версии API не должно нарушать работу существующих клиентов.

## Формат данных

Все запросы и ответы используют `application/json`.

## Общая структура

REST API первого этапа состоит из следующих разделов:

- Catalog API;
- Publication API;
- Seller API;
- Admin API;
- System API.

## Catalog API

Используется Buyer Web.

- `GET /api/v1/catalog/groups` — дерево категорий (ProductGroup) с количеством товаров.
- `GET /api/v1/catalog/products` — товары категории; параметры `group_id`, `page`, `limit`, `search`. Ответ содержит Product, минимальную цену, количество предложений, фотографии.
- `GET /api/v1/catalog/products/{id}` — карточка товара: Product, список SellerProduct, цены, остатки, фотографии.

## Publication API

Используется Seller Cabinet.

- `POST /api/v1/publications` — создание публикации. `Content-Type: application/json`, тело `{"access_token": str, "sheet_url": str}` (либо `spreadsheet_id` вместо `sheet_url`). Сервер резолвит `access_token` в `seller_id`/`published_by` (таблица `Seller`, см. Seller API — `POST /activate`) — клиент их не передаёт напрямую (закрыто 19.07 — была дыра безопасности, открытый `seller_id` позволял публиковать от чужого имени). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации (`publication_id`, `created`, `updated`, `deactivated`, `mode`, `hidden_no_photo`), либо список ошибок валидации (`422`). `hidden_no_photo` — список названий товаров, сохранённых в каталог продавца, но не показанных покупателю из-за пустой колонки «Фото» (`is_published = FALSE`); публикация при этом считается успешной, а `deactivated` такие строки не учитывает — он считает только товары, исчезнувшие из книги. Нормативное правило — [Publication_Model.md](../02-domain/Publication_Model.md), раздел «Видимость предложения в Buyer Catalog»; изменение шаблона — [Seller_Workspace.md](../05-ui/Seller_Workspace.md), запись от 2026-08-02.
- `GET /api/v1/publications?access_token=...` — история публикаций продавца, версии по убыванию (`version`, `published_at`, `created`, `updated`, `deactivated`).
- `POST /api/v1/photos` — загрузка фотографии товара. `Content-Type: multipart/form-data`, поля `access_token` (str) + `file` (изображение, `image/jpeg`/`image/png`/`image/webp`, до 10 МБ). Сервер резолвит `access_token` в `seller_id` (та же таблица `Seller`, что и остальной Publication/Seller API), загружает файл в S3, создаёт запись `Photo`. Ответ `201` — `{"photo_id": int}`. Endpoint не связывает фото с товаром — связь появляется только при следующей публикации каталога через колонку «Фото» (см. [Catalog_Template.md](../02-domain/Catalog_Template.md)).

## Seller API

Используется Seller Cabinet (и Apps Script карточки товара — обмен `activation_code` на `access_token`, см. `apps_script/product_card/`).

- `POST /api/v1/seller/activate` — первичная привязка персональной копии Google Sheets к продавцу. Тело `{"activation_code": str, "spreadsheet_id": str}`. Ответ — `{"access_token": str}`, который клиент сохраняет и в дальнейшем передаёт как обычный `access_token` во все остальные Seller/Publication-эндпоинты. Код активации одноразовый, с TTL (7 дней), выдаётся администратором через `POST /api/v1/admin/sellers` (см. Admin API) — самостоятельной регистрации нет, `Seller.user_id` обязан ссылаться на уже существующего пользователя платформы (см. `Seller_Profile.md`, `003_create_seller.sql`).
- `GET /api/v1/seller/catalog?access_token=...` — статус-сводка продавца (`is_active`, `current_catalog_version`, `published_product_count`, `last_published_at`), не построчный список товаров.
- `GET /api/v1/seller/catalog/template` — шаблон Excel. Не реализовано — актуальный источник шаблона (CR-001) — статическая Google-таблица, не Excel-файл через API.
- `GET /api/v1/seller/catalog/errors` — ошибки последней публикации. Не реализовано — ошибки сейчас возвращаются синхронно в ответе `POST /publications`, отдельный запрос не требовался.

## Admin API

Используется Admin Cabinet.

**Аутентификация.** Все эндпоинты Admin API, кроме `POST /activate`, требуют заголовок `Authorization: Bearer <access_token>`. Токен в query-строке не принимается — в отличие от Seller API: query целиком пишется в access.log nginx, а права администратора шире (модерация всего каталога, а не одного продавца). Недействительный или отсутствующий токен — `401` с кодом `ADMIN_ACCESS_DENIED` (у продавца аналогичная ситуация даёт `403`: там токен идентифицирует уже известного продавца, здесь запрос просто неаутентифицирован).

Механизм повторяет продавцовский (одноразовый код → постоянный токен), но опирается на собственную таблицу `Administrator` (миграция 013). Платформенная роль `users.id_role` в доступе намеренно не участвует: иначе выдача админских прав требовала бы изменения роли на стороне платформы. `Administrator.user_id` обязателен по другой причине — `SellerProduct.moderator_id` — FK на `users(id_user)`, без платформенного пользователя модерация не смогла бы записать своего автора.

- `POST /api/v1/admin/activate` — обмен одноразового кода на постоянный токен. Тело `{"activation_code": str}`, ответ `{"access_token": str}`. Код одноразовый, с TTL (7 дней), выдаётся вне API (`scripts/issue_admin_activation_code.py <user_id>` — он же создаёт учётную запись администратора при первом вызове). Недействительный, просроченный, уже использованный код и отозванная учётка (`is_active = FALSE`) неразличимы в ответе — `400`, `INVALID_ACTIVATION_CODE`.
- `GET /api/v1/admin/me` — кто вызывает: `{"admin_id": int, "user_id": int}`. Используется Admin Cabinet для проверки токена без побочных эффектов.
- `GET/POST /api/v1/admin/product-groups`, `PUT /api/v1/admin/product-groups/{id}` — управление ProductGroup. Не реализовано.
- `GET/POST /api/v1/admin/products`, `PUT /api/v1/admin/products/{id}` — управление Product. Не реализовано.
- `POST /api/v1/admin/sellers` — **подключить пользователя платформы как продавца**. Тело `{"user_id": int}`, ответ `201` — `{"seller_id": int, "activation_code": str}`. Одна бизнес-операция: проверяет пользователя, создаёт `Seller`, выдаёт код активации. Рабочий токен не выдаётся — продавец получает его сам через `POST /api/v1/seller/activate`. Ошибки: `404` `USER_NOT_FOUND` (нет такого пользователя платформы), `409` `SELLER_ALREADY_EXISTS` (продавец уже подключён; `seller_id` существующего указан в сообщении, чтобы админ мог перевыпустить код).
- `POST /api/v1/admin/sellers/{id}/activation-code` — перевыпустить код активации (продавец потерял код или не успел до истечения TTL). Предыдущий код перестаёт действовать. Ответ — `{"seller_id": int, "activation_code": str}`, `404` `SELLER_NOT_FOUND`.
- `DELETE /api/v1/admin/sellers/{id}/activation-code` — отозвать невостребованный код. Ответ `204`. Уже выданный рабочий токен не трогает — это другая операция (деактивация продавца).
- `GET /api/v1/admin/sellers`, `PUT /api/v1/admin/sellers/{id}/activate`, `PUT /api/v1/admin/sellers/{id}/deactivate` — управление продавцами. Не реализовано.
- `GET /api/v1/admin/moderation`, `PUT /api/v1/admin/moderation/{id}` — очередь модерации (обработка SellerProduct без связи с Product). Не реализовано.

## System API

- `GET /health` — проверка работоспособности сервиса и доступности БД. **Единственный эндпоинт без префикса `/api/v1`** — он про сам процесс, а не про версионируемый прикладной контракт. Ответ при исправной БД: `{"status": "UP", "database": "UP"}`; если БД недоступна — `{"status": "DOWN", "database": "<текст ошибки>"}`, код ответа при этом остаётся `200` (проверяющий смотрит на тело, а не на статус).

## Коды ответа

Стандартные HTTP-коды:

| Код | Значение |
|---|---|
| `200` | успешно |
| `201` | создано |
| `400` | ошибка запроса |
| `401` | не авторизован |
| `403` | доступ запрещён |
| `404` | не найдено |
| `409` | конфликт |
| `422` | ошибка валидации |
| `500` | внутренняя ошибка |

## Ошибки

Все ошибки имеют единый формат:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": []
  }
}
```

## Совместимость

Добавление новых полей ответа допускается без изменения версии API. Удаление существующих полей или изменение их семантики требует выпуска новой версии API.

## Владение API

| Раздел | Владелец |
|---|---|
| Catalog API | Catalog Service |
| Publication API | Publication Service |
| Seller API | Publication Service |
| Admin API | Admin Module |
| System API | Platform |

## Основные принципы

Один ресурс — один endpoint. REST вместо RPC. Бизнес-логика не переносится в клиент. UI взаимодействует только через API. API отражает предметную модель, а не структуру базы данных.

Полные схемы запросов/ответов (JSON Schema / OpenAPI) в архитектурную документацию сознательно не включены — здесь описаны только ресурсы, методы, ответственность и контракт. Детализация поддерживается отдельно в `openapi.yaml`, генерируемом из кода или сопровождаемом параллельно, чтобы архитектурная документация оставалась стабильной.

## Связь с другими документами

Предметная модель определяется документом [Domain_Model.md](../02-domain/Domain_Model.md). Процесс публикации определяется документом [Publication_Service.md](Publication_Service.md). Алгоритм выполнения публикации определяется документом [Publication_Workflow.md](Publication_Workflow.md). Пользовательские сценарии определяются документами [Buyer_MVP.md](../05-ui/Buyer_MVP.md), [Seller_MVP.md](../05-ui/Seller_MVP.md) и [Admin_MVP.md](../05-ui/Admin_MVP.md).

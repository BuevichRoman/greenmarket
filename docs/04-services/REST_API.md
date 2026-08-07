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
- `GET /api/v1/catalog/sellers/{id}` — карточка продавца: `{"seller_id": int, "name": str, "row": str|null, "place": str|null, "working_hours": str|null, "short_description": str|null, "phone": str|null, "whatsapp": str|null}`. Состав — [Seller_Profile.md](../02-domain/Seller_Profile.md), §9. Деактивированный или несуществующий продавец — `404` `NOT_FOUND`: покупателю неактивный продавец не показывается (§9), и различать эти два случая незачем — иначе по кодам ответа можно было бы перебором выяснить, кто из продавцов деактивирован. Код `NOT_FOUND`, а не `SELLER_NOT_FOUND` как в Seller/Admin API, — сознательно: в Catalog API все 404 одинаковы (см. `GET /catalog/products/{id}`), покупателю не полагается различать причину. Учётный телефон платформы (`users.phone`) здесь не появляется никогда — отдаётся только то, что продавец сохранил сам.

## Publication API

Используется Seller Cabinet.

- `POST /api/v1/publications` — создание публикации. `Content-Type: application/json`, тело `{"access_token": str, "sheet_url": str}` (либо `spreadsheet_id` вместо `sheet_url`). Сервер резолвит `access_token` в `seller_id`/`published_by` (таблица `Seller`, см. Seller API — `POST /activate`) — клиент их не передаёт напрямую (закрыто 19.07 — была дыра безопасности, открытый `seller_id` позволял публиковать от чужого имени). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации (`publication_id`, `created`, `updated`, `deactivated`, `mode`, `hidden_no_photo`), либо список ошибок валидации (`422`). `hidden_no_photo` — список названий товаров, сохранённых в каталог продавца, но не показанных покупателю из-за пустой колонки «Фото» (`is_published = FALSE`); публикация при этом считается успешной, а `deactivated` такие строки не учитывает — он считает только товары, исчезнувшие из книги. Нормативное правило — [Publication_Model.md](../02-domain/Publication_Model.md), раздел «Видимость предложения в Buyer Catalog»; изменение шаблона — [Seller_Workspace.md](../05-ui/Seller_Workspace.md), запись от 2026-08-02.
- `GET /api/v1/publications?access_token=...` — история публикаций продавца, версии по убыванию (`version`, `published_at`, `created`, `updated`, `deactivated`).
- `POST /api/v1/photos` — загрузка фотографии товара. `Content-Type: multipart/form-data`, поля `access_token` (str) + `file` (изображение, `image/jpeg`/`image/png`/`image/webp`, до 10 МБ). Сервер резолвит `access_token` в `seller_id` (та же таблица `Seller`, что и остальной Publication/Seller API), загружает файл в S3, создаёт запись `Photo`. Ответ `201` — `{"photo_id": int}`. Endpoint не связывает фото с товаром — связь появляется только при следующей публикации каталога через колонку «Фото» (см. [Catalog_Template.md](../02-domain/Catalog_Template.md)).

## Seller API

Используется Seller Cabinet (и Apps Script карточки товара — обмен `activation_code` на `access_token`, см. `apps_script/product_card/`).

- `POST /api/v1/seller/activate` — первичная привязка персональной копии Google Sheets к продавцу. Тело `{"activation_code": str, "spreadsheet_id": str}`. Ответ — `{"access_token": str}`, который клиент сохраняет и в дальнейшем передаёт как обычный `access_token` во все остальные Seller/Publication-эндпоинты. Код активации одноразовый, с TTL (7 дней), выдаётся администратором через `POST /api/v1/admin/sellers` (см. Admin API) — самостоятельной регистрации нет, `Seller.user_id` обязан ссылаться на уже существующего пользователя платформы (см. `Seller_Profile.md`, `003_create_seller.sql`).
- `GET /api/v1/seller/catalog?access_token=...` — статус-сводка продавца (`is_active`, `current_catalog_version`, `published_product_count`, `last_published_at`), не построчный список товаров.
- `GET /api/v1/seller/profile?access_token=...` — профиль продавца для формы в рабочей книге: `{"seller_id": int, "name": str, "status": "ACTIVE"|"INACTIVE", "row": str|null, "place": str|null, "working_hours": str|null, "short_description": str|null, "phone": str|null, "whatsapp": str|null, "suggested_phone": str|null}`. `name` и `status` только для чтения: имя — учётное `users.name` платформы, статус меняется админскими `PUT /api/v1/admin/sellers/{id}/activate|deactivate`. `suggested_phone` — учётный телефон платформы, предлагаемый как заготовка, пока продавец не сохранил свой; в карточку покупателю он не попадает, и в `users` ничего не пишется (решение от 06.08.2026: `users.phone`/`users.wa` — учётные поля платформы с флагами верификации, витринный контакт продавца хранится отдельно). Деактивированный продавец профиль видит и правит: деактивация скрывает каталог от покупателей, но кабинет продавцу остаётся. `403` `SELLER_ACCESS_DENIED`, `404` `SELLER_NOT_FOUND`.
- `PUT /api/v1/seller/profile` — сохранение профиля. Тело `{"access_token": str, "row": str|null, ...}`; правятся только переданные ключи, отсутствие ключа означает «не трогать», а `null`, пустая строка и строка из пробелов одинаково очищают поле. Лишние ключи в теле запрещены (`extra="forbid"`): молчаливое игнорирование опечатки в имени поля неотличимо от успешного сохранения. Ответ — `{"changed": [str]}`, имена реально изменившихся полей в порядке их объявления в профиле; повторная отправка тех же значений возвращает пустой список — это успех, а не отказ, и в журнал ничего не пишется. `403` `SELLER_ACCESS_DENIED`, `404` `SELLER_NOT_FOUND` (токен резолвится, но продавца с таким `seller_id` нет), `422` `VALIDATION_ERROR` при неизвестном поле или превышении длины.
- `GET /api/v1/seller/catalog/template` — шаблон Excel. Не реализовано — актуальный источник шаблона (CR-001) — статическая Google-таблица, не Excel-файл через API.
- `GET /api/v1/seller/catalog/errors` — ошибки последней публикации. Не реализовано — ошибки сейчас возвращаются синхронно в ответе `POST /publications`, отдельный запрос не требовался.

## Admin API

Используется Admin Cabinet.

**Аутентификация.** Все эндпоинты Admin API, кроме `POST /activate`, требуют заголовок `Authorization: Bearer <access_token>`. Токен в query-строке не принимается — в отличие от Seller API: query целиком пишется в access.log nginx, а права администратора шире (модерация всего каталога, а не одного продавца). Недействительный или отсутствующий токен — `401` с кодом `ADMIN_ACCESS_DENIED` (у продавца аналогичная ситуация даёт `403`: там токен идентифицирует уже известного продавца, здесь запрос просто неаутентифицирован).

Механизм повторяет продавцовский (одноразовый код → постоянный токен), но опирается на собственную таблицу `Administrator` (миграция 013). Платформенная роль `users.id_role` в доступе намеренно не участвует: иначе выдача админских прав требовала бы изменения роли на стороне платформы. `Administrator.user_id` обязателен по другой причине — `SellerProduct.moderator_id` — FK на `users(id_user)`, без платформенного пользователя модерация не смогла бы записать своего автора.

- `POST /api/v1/admin/activate` — обмен одноразового кода на постоянный токен. Тело `{"activation_code": str}`, ответ `{"access_token": str}`. Код одноразовый, с TTL (7 дней), выдаётся вне API (`scripts/issue_admin_activation_code.py <user_id>` — он же создаёт учётную запись администратора при первом вызове). Недействительный, просроченный, уже использованный код и отозванная учётка (`is_active = FALSE`) неразличимы в ответе — `400`, `INVALID_ACTIVATION_CODE`.
- `GET /api/v1/admin/me` — кто вызывает: `{"admin_id": int, "user_id": int}`. Используется Admin Cabinet для проверки токена без побочных эффектов.
- `GET /api/v1/admin/product-groups` — плоский список групп: `{"groups": [{"id": int, "parent_id": int|null, "name": str, "sort_order": int, "is_active": bool, "product_count": int}]}`. Дерево собирает интерфейс. В отличие от `GET /api/v1/catalog/groups` список включает деактивированные группы — иначе скрытую группу нечем вернуть в работу.
- `POST /api/v1/admin/product-groups` — тело `{"name": str, "parent_id": int|null, "sort_order": int}` (`parent_id` и `sort_order` необязательны), ответ `201` — объект группы. `404` `PRODUCT_GROUP_NOT_FOUND`, если родителя не существует.
- `PUT /api/v1/admin/product-groups/{id}` — переименование, перенос, `sort_order`, `is_active`. Правятся только поля, переданные в теле; `{"parent_id": null}` переносит группу в корень, отсутствие ключа оставляет родителя как есть. `404` `PRODUCT_GROUP_NOT_FOUND`; `400` `INVALID_PARENT_GROUP` при переносе группы под саму себя или собственного потомка (иначе ветка отрывается от дерева).
- `GET /api/v1/admin/products` — справочник: `?group_id=`, `?query=` (поиск по наименованию), `?page=`, `?limit=`. Ответ — `{"products": [{"id": int, "product_group_id": int, "group_name": str, "name": str, "description": str|null, "is_active": bool, "offer_count": int}], "page": int, "limit": int, "total": int}`. Включает деактивированные позиции; `offer_count` — число связанных `SellerProduct` (удаление `Product` при связанных предложениях не допускается, см. `Admin_MVP.md`).
- `POST /api/v1/admin/products` — тело `{"product_group_id": int, "name": str, "description": str|null}`, ответ `201` — объект позиции. `404` `PRODUCT_GROUP_NOT_FOUND`. Одноимённые позиции допустимы (`UNIQUE(name)` в схеме сознательно нет, см. `002_create_products.sql`).
- `PUT /api/v1/admin/products/{id}` — наименование, описание, перенос между группами, `is_active`. `404` `PRODUCT_NOT_FOUND`, `404` `PRODUCT_GROUP_NOT_FOUND` при переносе в несуществующую группу. `DELETE` не предусмотрен — вместо удаления `is_active = FALSE`.
- `POST /api/v1/admin/sellers` — **подключить пользователя платформы как продавца**. Тело `{"user_id": int}`, ответ `201` — `{"seller_id": int, "activation_code": str}`. Одна бизнес-операция: проверяет пользователя, создаёт `Seller`, выдаёт код активации. Рабочий токен не выдаётся — продавец получает его сам через `POST /api/v1/seller/activate`. Ошибки: `404` `USER_NOT_FOUND` (нет такого пользователя платформы), `409` `SELLER_ALREADY_EXISTS` (продавец уже подключён; `seller_id` существующего указан в сообщении, чтобы админ мог перевыпустить код).
- `POST /api/v1/admin/sellers/{id}/activation-code` — перевыпустить код активации (продавец потерял код или не успел до истечения TTL). Предыдущий код перестаёт действовать. Ответ — `{"seller_id": int, "activation_code": str}`, `404` `SELLER_NOT_FOUND`.
- `DELETE /api/v1/admin/sellers/{id}/activation-code` — отозвать невостребованный код. Ответ `204`. Уже выданный рабочий токен не трогает — это другая операция (деактивация продавца).
- `GET /api/v1/admin/sellers` — список подключённых продавцов, отсортированный по `seller_id`. Ответ — `{"sellers": [{"seller_id": int, "user_id": int, "name": str, "is_active": bool, "current_catalog_version": int, "activated_at": datetime|null, "activation_code_expires_at": datetime|null}]}`. `name` — отображаемое имя из платформенной `users` (см. `Seller_Profile.md`). `activated_at` и `activation_code_expires_at` вместе показывают шаг подключения: код выдан, но `activated_at` пуст — продавец ещё не обменял код на токен.
- `PUT /api/v1/admin/sellers/{id}/activate`, `PUT /api/v1/admin/sellers/{id}/deactivate` — возврат в активное состояние и временная деактивация (см. `Admin_MVP.md`). Деактивация скрывает каталог продавца от покупателей; публикации, `SellerProduct` и история сохраняются, повторная активация возвращает последнюю опубликованную версию без повторной публикации. Самого продавца деактивация не отключает: его `access_token` продолжает действовать, кабинет и публикация каталога ему остаются (решение от 2026-08-05) — видимость покупателю фильтруется отдельно. Ответ — объект продавца того же вида, что в списке. Операции идемпотентны. `404` `SELLER_NOT_FOUND`.
- `GET /api/v1/admin/sellers/{id}/profile` — профиль продавца для админской формы редактирования: тот же состав, что у `GET /api/v1/seller/profile`, **без** `suggested_phone` (это заготовка для первого заполнения продавцом, админу она не нужна). В отличие от карточки покупателя отдаёт и деактивированного продавца — админ правит в первую очередь именно таких, ради этого в ответе есть `status`. `404` `SELLER_NOT_FOUND`.
- `PUT /api/v1/admin/sellers/{id}/profile` — правка профиля продавца администратором. Тело — те же поля, что у `PUT /api/v1/seller/profile`, без `access_token` (админ аутентифицируется заголовком) и с тем же запретом лишних ключей. Ответ — `{"seller_id": int, "changed": [str]}`. В журнале автором записывается администратор (`author_role = "ADMIN"`, `author_user_id` — его платформенный `users.id_user`). `404` `SELLER_NOT_FOUND`, `422` `VALIDATION_ERROR`.
- `GET /api/v1/admin/profile-changes?limit=&after_id=` — лента последних изменений профилей, новые первыми. `limit` по умолчанию 50, минимум 1, максимум 200. Ответ — `{"changes": [{"id": int, "seller_id": int, "seller_name": str, "field": str, "old_value": str|null, "new_value": str|null, "author_user_id": int, "author_role": "SELLER"|"ADMIN", "created_at": datetime}], "total": int}`. `after_id` возвращает только записи с бо́льшим `id` — это «что нового с прошлого раза»: клиент запоминает максимальный `id` предыдущей выдачи. `total` считается с учётом `after_id` и позволяет отличить полную страницу от обрезанной. Лента глобальная, по всем продавцам, сортировка по `id`, а не по `created_at`: несколько полей, изменённых одним запросом, получают одинаковую метку времени с точностью до секунды. Это осознанно pull, а не push: механизма уведомлений (почта, мессенджер) в системе нет, и лента принята коллегой как достаточная для Stage 1.
- `GET /api/v1/admin/moderation` — очередь модерации: предложения продавцов без связи с `Product`, старые первыми. Параметры `?page=`, `?limit=`. Ответ — `{"items": [{"seller_product_id": int, "seller_id": int, "seller_name": str, "name": str, "description": str|null, "price": Decimal, "unit": str, "is_published": bool, "moderation_status": str, "created_at": datetime, "photos": [str]}], "page": int, "limit": int, "total": int}`. `seller_name` — имя продавца (как в Catalog API), `name` — наименование товара, данное продавцом (столбец `SellerProduct.seller_name`). Очередь строится по `product_id IS NULL`, а не по значению `moderation_status`: статус выводится из связи (см. `014_fix_moderation_status_invariant.sql`).
- `PUT /api/v1/admin/moderation/{id}` — привязать предложение к позиции справочника. Тело `{"product_id": int, "comment": str|null}`. Проставляет `product_id`, `moderator_id` (пользователь платформы из токена админа), `moderated_at`, при наличии — `moderation_comment`; статус становится `RESOLVED`, позиция уходит из очереди и появляется в каталоге покупателя. Ошибки: `404` `SELLER_PRODUCT_NOT_FOUND`, `404` `PRODUCT_NOT_FOUND`, `400` `INACTIVE_PRODUCT` (привязка к деактивированной позиции выглядела бы как завершённая модерация, но покупателю товар всё равно не показывался бы).

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

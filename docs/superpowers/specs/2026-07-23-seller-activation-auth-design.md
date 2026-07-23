# Design: Авторизация продавца через activation code (замена статического access_token)

**Дата:** 2026-07-23
**Статус:** Approved (Roman), собственная инициатива — не отправляется коллеге на согласование (закрывает известный техдолг, спеки на этот счёт от коллеги нет).

## Контекст

Сейчас `access_token` продавца — статическая запись в `SELLER_ACCESS_TOKENS` (JSON в `.env` сервера, не в git): `{"<token>": {"seller_id": ..., "published_by": ..., "name": ...}}`. Резолвится через `resolve_seller_access()` (`backend/app/publication/seller_access.py`). Используется в 4 местах: `POST /api/v1/publications`, `GET /api/v1/seller/catalog`, `GET /api/v1/publications`, `POST /api/v1/photos`, плюс Apps Script карточки товара (`apps_script/product_card/Code.gs`, `ACCESS_TOKEN_PROPERTY` в `PropertiesService`).

Проблемы текущей схемы:
- выдача/отзыв — ручное редактирование JSON на сервере (SSH), не масштабируется;
- нет ротации, нет TTL, нет audit-триггера («когда токен реально выдан продавцу»);
- сам `access_token` — секрет, который вручную копируют в URL (`?token=...`) и в Apps Script editor — раскрывается человеку напрямую.

Реальная рабочая модель продавца (уточнено Романом 23.07): мастер-таблица (сейчас `12fOFHg9iy...Ku4`, см. [[greenmarket-primary-seller-workspace]]) всегда пустая, продавцу доступна только на чтение. Продавец жмёт «Файл → Скопировать», получает свою уникальную рабочую книгу — именно с ней он работает дальше. Новая авторизация встраивается в этот момент: копия должна сама «представиться» бэкенду и получить свой персональный `access_token`, не через ручную правку `PropertiesService` админом.

Рассмотренные и отклонённые варианты (см. обсуждение в сессии 2026-07-23):
- **Seller самозаписывается по `spreadsheet_id`, без кода** — технически красиво, но ломает модель безопасности: `Seller.user_id` обязан ссылаться на существующего `aristotel_taxi.users.id_user` (роль Водитель, миграция `003_create_seller.sql`, комментарий «отдельная регистрация продавцов вне платформенной идентификации не производится») — самостоятельная регистрация в принципе противоречит этому архитектурному решению, любой обладатель ссылки на шаблон мог бы назначить себя продавцом.
- **SMS/WhatsApp OTP** — правильная «настоящая» авторизация, но требует внешнего провайдера (расходы, регистрация юрлица для РФ-номеров), не оправдано для этого цикла (нет срочности, чинится собственная инициатива).

## Архитектура

Двухуровневая модель секретов:
- **Activation code** — одноразовый, короткоживущий (TTL), только для первичной привязки конкретной копии таблицы к `Seller`. Показывается/передаётся продавцу человеком (Роман, через WhatsApp/телефон — оба поля обязательны по `Seller_Profile.md`).
- **Access token** — постоянный рабочий секрет для публикации/фото/статуса. Продавцу никогда не показывается — Apps Script получает его от backend один раз при активации и хранит в `PropertiesService`.

Важное архитектурное наблюдение: Google Sheets **не копирует Document Properties** при «Скопировать таблицу» — новая копия продавца всегда стартует с пустым `PropertiesService.getDocumentProperties()`. Мастер-таблица физически не может передать свой токен в копии (в ней и не должно быть токена — она предназначена только для чтения/копирования, не для работы). Это даёт естественный, бесплатный сигнал «эта копия ещё не активирована».

`SELLER_ACCESS_TOKENS`/`.env`-конфиг полностью упраздняется — весь резолвинг переезжает в БД.

## Schema

Новая миграция `database/migrations/011_alter_seller_add_activation.sql`, аддитивная к `Seller` (создана `003_create_seller.sql`):

```sql
ALTER TABLE Seller
    ADD COLUMN access_token               VARCHAR(64)  NULL COMMENT 'Постоянный рабочий токен продавца (заменяет SELLER_ACCESS_TOKENS)',
    ADD COLUMN activation_code            VARCHAR(32)  NULL COMMENT 'Одноразовый код первичной привязки, NULL после использования',
    ADD COLUMN activation_code_expires_at DATETIME     NULL COMMENT 'TTL кода активации',
    ADD COLUMN spreadsheet_id             VARCHAR(100) NULL COMMENT 'ID персональной копии Google Sheets продавца (справочно, не проверяется на каждый запрос)',
    ADD COLUMN activated_at               DATETIME     NULL COMMENT 'Когда код активации был использован',
    ADD UNIQUE INDEX uk_Seller_access_token (access_token),
    ADD UNIQUE INDEX uk_Seller_activation_code (activation_code);
```

`spreadsheet_id` — справочное поле для админа («какая именно таблица у этого продавца сейчас рабочая»), не участвует в проверке доступа на каждый запрос (не привязываем `access_token` жёстко к одному `spreadsheet_id` — усложнение без явной пользы на Stage 1; при необходимости ужесточить — отдельный заход).

`backend/app/infrastructure/models.py` не меняется — `Seller` по-прежнему не ORM-модель (Anti-Corruption Layer, решение коллеги, см. `SellerGateway`), новые поля читаются/пишутся тем же способом (raw SQL) через расширение `SellerGateway`/`seller_access.py`.

## Backend

### `backend/scripts/issue_activation_code.py` (новый, admin-only CLI)

Принимает `seller_id` (уже существующий, создан отдельно — вне объёма этого design, ручной SQL/существующий процесс). Генерирует `activation_code` (например `secrets.token_hex(4)` → 8 hex-символов, читаемо для ручной передачи), `activation_code_expires_at = now() + 7 days`. Затирает предыдущий код, если был (переактивация = просто перезапуск скрипта). Печатает код в консоль для ручной отправки продавцу — Admin Cabinet (UI) не строится в этом цикле, `REST_API.md`'s Admin API остаётся нереализованным как и раньше.

### `resolve_seller_access()` (`backend/app/publication/seller_access.py`) — переписывается на DB

```python
def resolve_seller_access(access_token: str, session: Session) -> SellerAccess | None:
    row = session.execute(
        text(
            "SELECT s.id, s.user_id, u.name FROM Seller s "
            "JOIN users u ON u.id_user = s.user_id "
            "WHERE s.access_token = :token AND s.is_active = TRUE"
        ),
        {"token": access_token},
    ).first()
    if row is None:
        return None
    return SellerAccess(seller_id=row[0], published_by=row[1], name=row[2])
```

`SellerAccess` dataclass не меняется. Сигнатура меняется (`tokens_json` убирается, добавляется обязательный `session: Session`) — все 4 существующих вызывающих места (`publications.py` x2, `seller.py`, `photos.py`) уже держат `session` в своей области видимости (FastAPI dependency), правка сводится к добавлению аргумента в каждый вызов. `name` теперь берётся из `users.name` (платформенная таблица) вместо ручной записи в JSON — раньше это поле нигде фактически не отображалось (проверено — используется только в тестах), теперь становится живым.

### Новый endpoint: `POST /api/v1/seller/activate`

```json
// Запрос
{"activation_code": "a1b2c3d4", "spreadsheet_id": "1AbC...xyz"}

// Успех (200)
{"access_token": "..."}

// Ошибка (400) — код неверный, просрочен или уже использован (единый ответ, без уточнения причины)
{"error": {"code": "INVALID_ACTIVATION_CODE", "message": "Код активации недействителен.", "details": []}}
```

Логика: найти `Seller` по `activation_code`, проверить `activation_code_expires_at > now()`, сгенерировать `access_token = secrets.token_urlsafe(32)`, записать `access_token`/`spreadsheet_id`/`activated_at`, обнулить `activation_code`/`activation_code_expires_at` (делает код одноразовым). Не находит совпадение или код просрочен → 400, один и тот же код/сообщение (не даём отличить «неверный» от «просроченный» — не помогаем перебору).

### Документация

`REST_API.md`, раздел Seller API — добавить:
```
- `POST /api/v1/seller/activate` — первичная привязка персональной копии Google Sheets к продавцу. Тело `{"activation_code": str, "spreadsheet_id": str}`. Ответ — `access_token`, который клиент (Apps Script) сохраняет и в дальнейшем передаёт как обычный `access_token` во все остальные Seller/Publication-эндпоинты. Код активации одноразовый и выдаётся администратором вне API (нет самостоятельной регистрации — см. `Seller_Profile.md`/`003_create_seller.sql`).
```

## Apps Script (`apps_script/product_card/Code.gs`)

- `onOpen()` — если `PropertiesService.getDocumentProperties().getProperty(ACCESS_TOKEN_PROPERTY)` пуст, меню показывает «Активировать доступ» вместо «Открыть карточку»/«Добавить товар» (карточка недоступна без токена).
- Новая функция `activateAccess()`: модальный prompt (`SpreadsheetApp.getUi().prompt(...)`) на ввод `activation_code` → вызывает `POST /seller/activate` с `SpreadsheetApp.getActiveSpreadsheet().getId()` → при успехе сохраняет `access_token` в `PropertiesService`, показывает alert «Доступ активирован», подсказывает перезагрузить таблицу (чтобы `onOpen()` перерисовал меню). При ошибке — alert с текстом от backend.
- Новый пункт меню «Личный кабинет» (виден только когда токен уже сохранён) — Apps Script не может программно открыть внешний URL в новой вкладке, поэтому решение фиксированное: небольшой модальный HTML-диалог (`HtmlService.createHtmlOutput`) с одной кликабельной ссылкой `<a href="..." target="_blank">Открыть личный кабинет</a>`, где `href` — `Utilities.formatString('%s?token=%s', SELLER_CABINET_URL, token)`.

Seller Cabinet (React) **не меняется** — как принимал `?token=...` из URL, так и принимает; меняется только то, откуда эта ссылка теперь берётся (генерируется из уже активированной таблицы, а не рассылается админом вручную).

## Ротация и отзыв

- **Отзыв:** админ выставляет `Seller.is_active = FALSE` (поле уже существует) — `resolve_seller_access()` сразу перестаёт резолвить, мгновенный лок на всех 4 эндпоинтах.
- **Ротация/переактивация** (например, продавец потерял копию таблицы, завёл новую): админ повторно запускает `issue_activation_code.py` для того же `seller_id` — генерирует новый `activation_code`, затирая предыдущий (если не использован) или создавая новый цикл (если предыдущий уже был активирован, старый `access_token` при этом не трогается, пока explicitly не перевыпущен). Продавец в новой копии проходит `activateAccess()` — получает новый `access_token`, перезаписывающий старый в БД (значит старая копия с прежним токеном перестаёт работать после этого момента — ожидаемо, если продавец действительно сменил таблицу).

## Тестирование

Backend — TDD, интеграционные тесты на реальной MySQL (паттерн `committing_session`, как в остальных Publication-тестах):
- `resolve_seller_access()`: валидный токен → `SellerAccess` с именем из `users.name`; невалидный/неактивный продавец → `None`.
- `POST /seller/activate`: валидный код → 200 + рабочий `access_token`, код становится непригоден для повторного использования; просроченный код → 400; несуществующий код → 400 (тот же код ошибки); после успешной активации — новый `access_token` действительно резолвится в остальных эндпоинтах (`GET /seller/catalog` и т.п.) в том же тесте, сквозной сценарий.
- `issue_activation_code.py` — модульный тест на генерацию (уникальность, TTL выставлен верно, перезапись предыдущего кода).

Apps Script — вручную в браузере (нет JS-тестовой инфраструктуры на фронтах, как и в прошлых design-ах этого проекта): скопировать мастер-таблицу, убедиться что меню показывает только «Активировать доступ», пройти активацию реальным кодом, убедиться что меню переключилось на «Открыть карточку»/«Добавить товар»/«Личный кабинет», проверить что ссылка личного кабинета реально открывает Seller Cabinet с рабочим токеном.

## Definition of Done

- Миграция 011 применена локально, синхронизирована с CI/тестовыми фикстурами и локальным Docker (по опыту прошлых миграций — `tests/fixtures/`, `backend-ci.yml` глоб миграций, `greenmarket-mysql`).
- `SELLER_ACCESS_TOKENS`/`.env`-конфиг удалён из кода и с сервера после переноса существующих (демо) токенов в БД вручную.
- `POST /api/v1/seller/activate` реализован, покрыт интеграционными тестами, весь набор тестов зелёный.
- `REST_API.md` синхронизирован (новый endpoint документирован).
- Apps Script проверен вручную сквозным сценарием (копия → активация → карточка/личный кабинет работают) минимум на одном реальном демо-продавце.
- `issue_activation_code.py` даёт админу (Роману) рабочий способ выдавать/переактивировать доступ без правки `.env`/SQL руками.

## Вне объёма (сознательно)

- Admin Cabinet (UI для выдачи кодов) — `issue_activation_code.py`-скрипт достаточен для текущего масштаба (единицы продавцов), полноценный `Admin API`/UI из `REST_API.md` остаётся нереализованным, как и раньше.
- SMS/WhatsApp OTP — переоценивать в будущем, если появится реальное давление со стороны безопасности/масштаба; сейчас не оправдано (см. «Контекст»).
- Жёсткая привязка `access_token` к конкретному `spreadsheet_id` (проверка на каждый запрос) — `spreadsheet_id` хранится справочно, не форсируется.
- Автоматическое обнаружение/повторная активация при смене таблицы продавцом без участия админа — всегда требует нового `activation_code`, выданного человеком.

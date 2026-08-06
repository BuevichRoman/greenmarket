# Seller Profile Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Продавец сам заполняет свой профиль (ряд, место, часы работы, описание, телефон, WhatsApp), админ может исправить, покупатель видит карточку продавца — с журналом изменений, по которому админ видит, кто что поменял.

**Architecture:** Значения профиля хранятся не своей таблицей, а платформенным механизмом расширяемых свойств `users_prop` + `users_prop_items_varchar|text` (решение Валентина 05–06.08.2026). GreenMarket обращается к этим таблицам только через Anti-Corruption Layer `UserPropGateway` — тем же паттерном, что `SellerGateway`/`PhotoGateway`. Собственная таблица GreenMarket здесь ровно одна — журнал изменений `SellerProfileChange`: в `users_prop_items_*` физически нет ни автора, ни времени (там только `id_users_prop`, `id_user`, `value`). Состав полей задаётся одним модулем `app/profile/fields.py`, который используют все три потребителя (продавец, админ, покупатель) — иначе набор полей разъедется по трём файлам.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (Database First — ORM только для таблиц GreenMarket, платформенные таблицы через `text()`), MySQL 8.0, pytest.

---

## Контекст: что уже сделано и что менять нельзя

**Свойства уже заведены на проде** (06.08.2026), схема `aristotel_taxi` — та же, где живут таблицы GreenMarket:

| id_users_prop | var | value_type | visibility | roles_edit |
|---|---|---|---|---|
| 5 | `gm_seller_row` | 1 (varchar) | 15 | 2, 4 |
| 6 | `gm_seller_place` | 1 (varchar) | 15 | 2, 4 |
| 7 | `gm_seller_working_hours` | 1 (varchar) | 15 | 2, 4 |
| 8 | `gm_seller_short_description` | 2 (text) | 15 | 2, 4 |
| 9 | `gm_seller_phone` | 1 (varchar) | 15 | 2, 4 |
| 10 | `gm_seller_whatsapp` | 1 (varchar) | 15 | 2, 4 |

**Правило: `id_users_prop` в коде не хардкодить никогда.** Свойство всегда резолвится по `var`. Локальная и боевая БД совпадают по id случайно, и на это опираться нельзя.

Реальная схема платформенных таблиц (снята с прода 06.08):

```sql
users_prop(id_users_prop INT PK AI, var VARCHAR(150) UNIQUE, name_ru..name_es VARCHAR(255) UNIQUE NULL,
           description_ru..description_es TEXT NOT NULL, active TINYINT(1) NOT NULL DEFAULT 1,
           value_type INT NOT NULL DEFAULT 1 FK field_type, `some` TINYINT(1) NOT NULL DEFAULT 0,
           visibility TINYINT(1) NOT NULL DEFAULT 12)
users_prop_items_varchar(id_users_prop INT, id_user INT, value VARCHAR(255) NOT NULL, PK(id_user, id_users_prop))
users_prop_items_text(id_users_prop INT, id_user INT, value TEXT NOT NULL, PK(id_user, id_users_prop))
users_prop_roles_edit(id_users_prop INT, id_role INT, PK(id_users_prop, id_role))
```

Обратить внимание: `value` — **NOT NULL**. «Пусто» = строки нет, а не `value = NULL`. Очистка поля — это `DELETE`, а не `UPDATE ... SET value = NULL`.

**Что выяснилось про предзаполнение из платформы** (запросы на проде 06.08, 570 пользователей):

- `users.phone` — тип **BIGINT** (не строка), заполнен у 449 из 570, но `phone_is_verified` только у 4. Длина от 1 до 17 цифр — то есть в колонке есть мусор.
- `users.wa` (varchar) и `users.wa_number` (bigint) — **0 заполненных строк на всю базу**. Источника для WhatsApp на платформе фактически нет.
- Из пяти продавцов GreenMarket телефон есть у одного (10 цифр, не верифицирован), WhatsApp — ни у кого.

Отсюда правило предзаполнения: `phone` подставляется из `users.phone` **только как подсказка в ответе GET, когда своего значения ещё нет**, и только если число похоже на номер (10–15 цифр). В `users` не пишем никогда. Для `whatsapp` предзаполнения нет — подставлять нечего.

**Состав профиля Stage 1** (`docs/02-domain/Seller_Profile.md`, §5, §7, §9):

| Поле API | Источник | Редактируется |
|---|---|---|
| `seller_id` | `Seller.id` | нет |
| `name` | `users.name` (платформа) | нет — это учётное имя платформы, тот же аргумент, что и по телефону |
| `status` | `Seller.is_active` → `ACTIVE`/`INACTIVE` | нет (отдельные админские эндпоинты activate/deactivate) |
| `row` | prop `gm_seller_row` | да |
| `place` | prop `gm_seller_place` | да |
| `working_hours` | prop `gm_seller_working_hours` | да |
| `short_description` | prop `gm_seller_short_description` | да |
| `phone` | prop `gm_seller_phone` | да |
| `whatsapp` | prop `gm_seller_whatsapp` | да |

`marketId` в профиле не хранится: на Stage 1 рынок один, справочник `Market` — Stage 2 (решение Валентина 06.08).

---

## Структура файлов

**Создаются:**

- `database/migrations/015_create_seller_profile_change.sql` — журнал изменений профиля.
- `backend/app/platform/user_prop_gateway.py` — ACL к `users_prop*` и к `users.phone`. Единственное место в кодовой базе, знающее имена платформенных prop-таблиц.
- `backend/app/profile/__init__.py`
- `backend/app/profile/fields.py` — определение полей профиля (имя поля → `var` свойства → тип значения → лимит длины). Единый источник для всех потребителей. Коды типов значений (`VALUE_TYPE_VARCHAR`/`VALUE_TYPE_TEXT`) объявлены не здесь, а в `user_prop_gateway.py`: это знание платформы (`users_prop.value_type` — FK на её словарь `field_type`), и зависимость идёт от продукта к ACL, а не наоборот.
- `backend/app/profile/seller_profile_service.py` — чтение профиля, применение изменений, запись журнала.
- `backend/app/profile/errors.py` — именованные исключения профиля (`UnknownProfileFieldError`, `ProfileValueTooLongError`, `SellerNotFoundError`) по образцу `app/publication/errors.py`. Заведены после ревью Task 6: без них до эндпоинта доезжали четыре разных состояния под одним `LookupError` — плохое поле от клиента (400), отсутствующий продавец (404) и два признака ненастроенного окружения из гейтвея (500). Плюс `KeyError` и `IndexError` сами наследуют `LookupError`, так что обычный баг доложился бы пользователю как «продавец не найден».
- `backend/app/infrastructure/repositories/seller_profile_change_repository.py` — журнал.
- `backend/app/api/v1/admin_profile.py` — админская правка профиля и лента изменений (в `admin.py` не дописываем — там уже онбординг и справочники, файл разделён по темам: `admin_catalog.py`, `admin_moderation.py`).
- `backend/tests/test_user_prop_gateway.py`
- `backend/tests/test_profile_fields.py`
- `backend/tests/test_seller_profile_service.py`
- `backend/tests/test_seller_profile_api.py`
- `backend/tests/test_admin_profile_api.py`

**Изменяются:**

- `backend/tests/fixtures/platform_stub.sql` — добавить `users.phone`/`users.wa` и стабы prop-таблиц.
- `backend/app/infrastructure/models.py` — модель `SellerProfileChange`.
- `backend/app/api/v1/seller_schemas.py` — схемы профиля.
- `backend/app/api/v1/seller.py` — `GET`/`PUT /api/v1/seller/profile`.
- `backend/app/api/v1/admin_schemas.py` — схемы админской правки и ленты.
- `backend/app/main.py` — подключить роутер `admin_profile`.
- `backend/app/api/v1/catalog_schemas.py`, `backend/app/api/v1/catalog.py`, `backend/app/application/catalog_use_case.py` — карточка продавца покупателю.
- `docs/04-services/REST_API.md` — описание новых эндпоинтов.
- `docs/02-domain/Seller_Profile.md` — раздел о том, где физически лежат поля.

**Не входит в этот план:** форма профиля в книге продавца (Apps Script) — отдельный план, делается после этого; он потребляет `GET`/`PUT /api/v1/seller/profile` как готовый контракт.

---

## Как запускать тесты

```bash
cd backend && uv run pytest tests/ -v
```

Тесты идут против настоящего MySQL в docker-контейнере `greenmarket-mysql` (порт 3307, схема из `backend/.env`). Фикстура `session` откатывается закрытием без commit; `committing_session` — через SAVEPOINT.

Пересоздать платформенный стаб после правки `platform_stub.sql`:

```bash
cd backend && set -a && . ./.env && set +a && docker exec -i -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" < tests/fixtures/platform_stub.sql
```

---

## Task 1: Платформенный стаб для prop-таблиц

**Files:**
- Modify: `backend/tests/fixtures/platform_stub.sql`

Локальная и CI-база сейчас содержат только `users(id_user, name)`. Без `users_prop*` ни один тест профиля не запустится. Стаб повторяет боевую схему по именам и типам колонок, но без FK на `field_type`/`users_roles` — этих словарей платформы у нас нет и код их не читает.

- [ ] **Step 1: Дописать стаб**

Добавить в конец `backend/tests/fixtures/platform_stub.sql`:

```sql
-- Колонки users, которые GreenMarket читает (никогда не пишет):
-- phone — предзаполнение витринного телефона в профиле продавца; BIGINT, как на платформе.
-- wa    — на боевой платформе не заполнена ни у одного пользователя, объявлена для полноты.
ALTER TABLE users
    ADD COLUMN phone BIGINT NULL
        COMMENT 'СТАБ: учётный телефон платформы, только для чтения',
    ADD COLUMN wa VARCHAR(255) NULL
        COMMENT 'СТАБ: учётный WhatsApp платформы, только для чтения';

-- СТАБ платформенного механизма расширяемых свойств пользователя.
-- Боевые таблицы живут в aristotel_taxi и созданы платформой; здесь только то,
-- что читает и пишет GreenMarket. FK на field_type/users_roles намеренно нет —
-- этих словарей у нас локально не существует, а код к ним не обращается.
CREATE TABLE users_prop
(
    id_users_prop  INT NOT NULL AUTO_INCREMENT,
    var            VARCHAR(150) NOT NULL,
    name_ru        VARCHAR(255) NULL,
    name_en        VARCHAR(255) NULL,
    active         TINYINT(1) NOT NULL DEFAULT 1,
    value_type     INT NOT NULL DEFAULT 1,
    `some`         TINYINT(1) NOT NULL DEFAULT 0,
    visibility     TINYINT(1) NOT NULL DEFAULT 12,
    PRIMARY KEY (id_users_prop),
    UNIQUE INDEX uk_users_prop_var (var)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop — только для тестов/dev';

CREATE TABLE users_prop_items_varchar
(
    id_users_prop INT NOT NULL,
    id_user       INT NOT NULL,
    value         VARCHAR(255) NOT NULL,
    PRIMARY KEY (id_user, id_users_prop)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop_items_varchar — только для тестов/dev';

CREATE TABLE users_prop_items_text
(
    id_users_prop INT NOT NULL,
    id_user       INT NOT NULL,
    value         TEXT NOT NULL,
    PRIMARY KEY (id_user, id_users_prop)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop_items_text — только для тестов/dev';

-- Определения свойств GreenMarket. На проде заведены вручную 06.08.2026
-- (users_prop — конфигурационная таблица платформы, не наша миграция).
-- Здесь повторены, чтобы локальная база вела себя как боевая.
-- value_type: 1 = varchar, 2 = text. visibility 15 = виден всем, включая
-- неавторизованного покупателя (см. COLUMN_COMMENT боевой users_prop.visibility).
INSERT INTO users_prop (var, name_ru, name_en, value_type, visibility) VALUES
    ('gm_seller_row',               'GreenMarket: ряд на рынке',              'GreenMarket: market row',        1, 15),
    ('gm_seller_place',             'GreenMarket: место на рынке',            'GreenMarket: market place',      1, 15),
    ('gm_seller_working_hours',     'GreenMarket: часы работы',               'GreenMarket: working hours',     1, 15),
    ('gm_seller_short_description', 'GreenMarket: краткое описание продавца', 'GreenMarket: short description', 2, 15),
    ('gm_seller_phone',             'GreenMarket: телефон продавца',          'GreenMarket: seller phone',      1, 15),
    ('gm_seller_whatsapp',          'GreenMarket: WhatsApp продавца',         'GreenMarket: seller WhatsApp',   1, 15);
```

- [ ] **Step 2: Применить стаб к локальной базе**

```bash
cd backend && set -a && . ./.env && set +a && docker exec -i -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" < tests/fixtures/platform_stub.sql
```

Файл начинается с `CREATE DATABASE IF NOT EXISTS greenmarket` и `USE greenmarket`, но `ALTER`/`CREATE TABLE` на уже существующей базе упадут с «Duplicate column» / «Table already exists». Поэтому применяем только новый кусок — скопировать добавленный SQL в отдельный файл и прогнать его, либо пересоздать базу с нуля:

```bash
cd backend && set -a && . ./.env && set +a && \
  docker exec -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" -e "DROP DATABASE IF EXISTS $DB_NAME;" && \
  docker exec -i -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" < tests/fixtures/platform_stub.sql && \
  MYSQL_BIN="docker exec -i -e MYSQL_PWD=$DB_PASSWORD greenmarket-mysql mysql" bash ../ci/apply-migrations.sh
```

Если `ci/apply-migrations.sh` не заводится через docker exec — применить миграции `database/migrations/*.sql` по порядку любым доступным способом; важен результат, а не команда.

- [ ] **Step 3: Проверить, что таблицы на месте**

```bash
cd backend && set -a && . ./.env && set +a && docker exec -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" -D"$DB_NAME" -t -e "SELECT var, value_type, visibility FROM users_prop ORDER BY id_users_prop;"
```

Expected: шесть строк `gm_seller_*`, `value_type` = 1 у всех кроме `gm_seller_short_description` (2).

- [ ] **Step 4: Убедиться, что старые тесты не сломались**

Run: `cd backend && uv run pytest tests/ -q`
Expected: PASS (столько же тестов, сколько до правки).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/platform_stub.sql
git commit -m "test: стаб платформенных users_prop для профиля продавца"
```

---

## Task 2: Миграция 015 — журнал изменений профиля

**Files:**
- Create: `database/migrations/015_create_seller_profile_change.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- Migration : 015_create_seller_profile_change.sql
-- Purpose   : Журнал изменений профиля продавца. Значения профиля лежат в
--             платформенном механизме свойств (users_prop_items_varchar|text),
--             но там физически нет ни автора, ни времени изменения — только
--             (id_users_prop, id_user, value). Валентин 06.08.2026 потребовал
--             «видеть, кто изменил», и лента этих записей в Admin Cabinet
--             принята им же вместо настоящих уведомлений (почта/мессенджер):
--             механизма уведомлений в системе не существует.
-- Note      : author_user_id — платформенный users.id_user, одинаково пригоден
--             и для продавца, и для администратора (Administrator.user_id тоже
--             ссылается на users). author_role различает их, потому что по
--             одному user_id этого не видно: админ технически тоже пользователь
--             платформы.
-- Note      : old_value/new_value NULL означает «значения не было» — в
--             users_prop_items_* колонка value объявлена NOT NULL, поэтому
--             пустое поле там представлено отсутствием строки, а не NULL.
-- Note      : author_role — VARCHAR с CHECK, а не ENUM: docs/03-database/
--             Coding_Standard.md, раздел «Статусы», запрещает ENUM, чтобы
--             расширение перечня не требовало изменения структуры БД. Образец —
--             chk_SellerProduct_moderation_status в 005_create_seller_products.sql.
-- DBMS      : MySQL Community Server 8.0.16+

CREATE TABLE SellerProfileChange
(
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    seller_id      BIGINT UNSIGNED NOT NULL
        COMMENT 'Продавец, чей профиль изменён (Seller.id)',

    field          VARCHAR(64) NOT NULL
        COMMENT 'Имя поля профиля в терминах API GreenMarket (row, place, working_hours, short_description, phone, whatsapp), а не var платформенного свойства',

    old_value      TEXT NULL
        COMMENT 'Значение до изменения; NULL — поле не было заполнено',

    new_value      TEXT NULL
        COMMENT 'Значение после изменения; NULL — поле очищено',

    author_user_id INT NOT NULL
        COMMENT 'Автор изменения в системе идентификации платформы (aristotel_taxi.users.id_user)',

    author_role    VARCHAR(16) NOT NULL
        COMMENT 'В какой роли автор внёс изменение: сам продавец из книги или администратор через Admin API',

    created_at     DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Когда изменение внесено (UTC)',

    PRIMARY KEY (id),

    INDEX idx_SellerProfileChange_feed (created_at DESC),
    INDEX idx_SellerProfileChange_seller (seller_id, created_at DESC),

    CONSTRAINT fk_SellerProfileChange_seller
        FOREIGN KEY (seller_id) REFERENCES Seller(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT fk_SellerProfileChange_author
        FOREIGN KEY (author_user_id) REFERENCES users(id_user)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT chk_SellerProfileChange_author_role CHECK
        (author_role IN ('SELLER', 'ADMIN'))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Журнал изменений полей профиля продавца';
```

- [ ] **Step 2: Применить локально**

```bash
cd backend && set -a && . ./.env && set +a && docker exec -i -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" -D"$DB_NAME" < ../database/migrations/015_create_seller_profile_change.sql
```

Expected: без ошибок.

- [ ] **Step 3: Проверить структуру**

```bash
cd backend && set -a && . ./.env && set +a && docker exec -e MYSQL_PWD="$DB_PASSWORD" greenmarket-mysql mysql -u"$DB_USER" -D"$DB_NAME" -e "SHOW CREATE TABLE SellerProfileChange\G"
```

Expected: два FK (`Seller`, `users`), `author_role` типа `varchar(16)` и ограничение `chk_SellerProfileChange_author_role`. Отдельно проверить, что CHECK работает: вставка строки с `author_role = 'ROBOT'` должна отвергаться MySQL.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/015_create_seller_profile_change.sql
git commit -m "feat: миграция 015 — журнал изменений профиля продавца"
```

---

## Task 3: Определение полей профиля

**Files:**
- Create: `backend/app/profile/__init__.py`, `backend/app/profile/fields.py`
- Test: `backend/tests/test_profile_fields.py`

> **Поправки после ревью (внесены при исполнении, приведённый ниже код им предшествует):**
> - `EDITABLE_FIELDS` **удалён**. Он был идентичен `PROFILE_FIELDS`, а комментарий объяснял разделение через `name`/`status`, которых в наборе нет — то есть различие существовало только на словах, зато вызывающий выбирал имя наугад. Везде дальше по плану, где написано `EDITABLE_FIELDS`, читать `PROFILE_FIELDS`.
> - `VALUE_TYPE_VARCHAR`/`VALUE_TYPE_TEXT` объявлены в `user_prop_gateway.py` (Task 4), а `fields.py` их импортирует — коды типов принадлежат платформе, а не продукту.
> - Тестовый файл называется `test_profile_fields.py`, а не `test_seller_profile_service.py`: он тестирует `fields.py`, сервис появляется только в Task 6 и заводит свой файл.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_seller_profile_service.py`:

```python
from app.profile.fields import EDITABLE_FIELDS, PROFILE_FIELDS, field_by_name


def test_editable_fields_cover_stage1_profile():
    assert [field.name for field in EDITABLE_FIELDS] == [
        "row",
        "place",
        "working_hours",
        "short_description",
        "phone",
        "whatsapp",
    ]


def test_every_field_maps_to_greenmarket_prop():
    for field in PROFILE_FIELDS:
        assert field.prop_var.startswith("gm_seller_")


def test_short_description_is_the_only_text_field():
    assert [field.name for field in PROFILE_FIELDS if field.value_type == 2] == ["short_description"]


def test_field_by_name_rejects_unknown_field():
    assert field_by_name("row") is not None
    assert field_by_name("id_role") is None
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.profile'`

- [ ] **Step 3: Реализовать**

Создать пустой `backend/app/profile/__init__.py` и `backend/app/profile/fields.py`:

```python
"""Состав профиля продавца — единственный источник правды.

Профиль читают и пишут три разных потребителя (книга продавца через Seller API,
администратор через Admin API, покупатель через Catalog API). Если набор полей
описать в каждом из них отдельно, он разъедется при первом же изменении, а
изменения тут будут: Stage 2 добавляет фото, логотип, соцсети и справочник
Market (Seller_Profile.md, §4 и §11).

Значения лежат в платформенном механизме свойств. `prop_var` — ключ свойства в
`users_prop.var`; числовой `id_users_prop` в коде не используется никогда, он
разный в разных базах.
"""

from dataclasses import dataclass

VALUE_TYPE_VARCHAR = 1
VALUE_TYPE_TEXT = 2


@dataclass(frozen=True)
class ProfileField:
    name: str
    prop_var: str
    value_type: int
    max_length: int


# max_length у varchar-полей равен ширине users_prop_items_varchar.value (255).
# short_description лежит в users_prop_items_text; ограничение 2000 — наше
# продуктовое, а не схемное: краткое описание в карточке продавца
# (Seller_Profile.md, §9), не статья.
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    ProfileField("row", "gm_seller_row", VALUE_TYPE_VARCHAR, 255),
    ProfileField("place", "gm_seller_place", VALUE_TYPE_VARCHAR, 255),
    ProfileField("working_hours", "gm_seller_working_hours", VALUE_TYPE_VARCHAR, 255),
    ProfileField("short_description", "gm_seller_short_description", VALUE_TYPE_TEXT, 2000),
    ProfileField("phone", "gm_seller_phone", VALUE_TYPE_VARCHAR, 255),
    ProfileField("whatsapp", "gm_seller_whatsapp", VALUE_TYPE_VARCHAR, 255),
)

# Пока редактируются все поля профиля, но список отделён намеренно: name и
# status тоже поля профиля (Seller_Profile.md, §5), просто владеет ими не
# GreenMarket — name это users.name платформы, status это Seller.is_active.
EDITABLE_FIELDS: tuple[ProfileField, ...] = PROFILE_FIELDS

_BY_NAME = {field.name: field for field in PROFILE_FIELDS}


def field_by_name(name: str) -> ProfileField | None:
    return _BY_NAME.get(name)
```

- [ ] **Step 4: Запустить тест**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: PASS (4 теста)

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile/__init__.py backend/app/profile/fields.py backend/tests/test_seller_profile_service.py
git commit -m "feat: определение полей профиля продавца"
```

---

## Task 4: UserPropGateway — доступ к платформенным свойствам

**Files:**
- Create: `backend/app/platform/user_prop_gateway.py`
- Test: `backend/tests/test_user_prop_gateway.py`

Тот же паттерн, что `SellerGateway` (`backend/app/platform/seller_gateway.py`): сырой SQL через `text()`, никаких ORM-моделей на платформенные таблицы, весь остальной код о существовании `users_prop*` не знает.

> **Поправки после ревью (внесены при исполнении, приведённый ниже код им предшествует):**
> - `VALUE_TYPE_VARCHAR`/`VALUE_TYPE_TEXT` объявлены здесь, а не импортируются из `fields.py` — иначе единственный файл в `app/platform/` зависел бы от продуктового модуля, и обещание докстринга «меняется только этот файл» было бы неправдой.
> - Добавлено исключение `UnsupportedPropTypeError` — раньше свойство с `value_type = 3` (в платформенном словаре `field_type` тройка есть, это int) давало голый `KeyError` из недр `_ITEMS_TABLE`.
> - `# noqa: S608` убран: в проекте нет ни ruff, ни flake8, директива под несуществующий линтер только сбивает с толку. Безопасность f-string объяснена комментарием над `_ITEMS_TABLE`.
> - `ON DUPLICATE KEY UPDATE value = VALUES(value)` заменено на `= :value`: `VALUES()` признана deprecated в MySQL 8.0.20+, локальный сервер 8.0.36 пишет предупреждение.
> - Набор тестов расширен сверх перечисленного ниже: физическая таблица под varchar- и text-свойство проверяется сырым SQL (иначе перепутанный маппинг `_ITEMS_TABLE` не роняет ни одного теста), изоляция значений по `id_user`, чтение списка свойств при частично заполненных значениях, `read` с пустым списком, `clear` по text-свойству и по несуществующей строке, верхняя граница правдоподобия телефона.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_user_prop_gateway.py`:

```python
import pytest
from sqlalchemy import text

from app.platform.user_prop_gateway import UnknownPropError, UserPropGateway


@pytest.fixture
def user_id(session) -> int:
    return session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для свойств"}
    ).lastrowid


def test_read_returns_empty_dict_when_nothing_stored(session, user_id):
    gateway = UserPropGateway(session)
    assert gateway.read(user_id, ["gm_seller_row", "gm_seller_place"]) == {}


def test_write_then_read_varchar(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    assert gateway.read(user_id, ["gm_seller_row"]) == {"gm_seller_row": "Ряд 3"}


def test_write_then_read_text(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_short_description", "Фермерское хозяйство с 2015 года")
    assert gateway.read(user_id, ["gm_seller_short_description"]) == {
        "gm_seller_short_description": "Фермерское хозяйство с 2015 года"
    }


def test_write_overwrites_existing_value(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_place", "Место 1")
    gateway.write(user_id, "gm_seller_place", "Место 2")
    assert gateway.read(user_id, ["gm_seller_place"]) == {"gm_seller_place": "Место 2"}


def test_clear_removes_row_because_value_is_not_nullable(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_phone", "+79990000000")
    gateway.clear(user_id, "gm_seller_phone")
    assert gateway.read(user_id, ["gm_seller_phone"]) == {}


def test_read_mixes_varchar_and_text_props(session, user_id):
    gateway = UserPropGateway(session)
    gateway.write(user_id, "gm_seller_row", "Ряд 3")
    gateway.write(user_id, "gm_seller_short_description", "Мёд и сыры")
    assert gateway.read(user_id, ["gm_seller_row", "gm_seller_short_description"]) == {
        "gm_seller_row": "Ряд 3",
        "gm_seller_short_description": "Мёд и сыры",
    }


def test_unknown_prop_var_raises(session, user_id):
    with pytest.raises(UnknownPropError):
        UserPropGateway(session).write(user_id, "gm_seller_nonexistent", "х")


def test_read_of_unknown_prop_var_raises(session, user_id):
    with pytest.raises(UnknownPropError):
        UserPropGateway(session).read(user_id, ["gm_seller_nonexistent"])


def test_platform_phone_returns_none_when_not_set(session, user_id):
    assert UserPropGateway(session).platform_phone(user_id) is None


def test_platform_phone_returns_digits_as_string(session, user_id):
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    assert UserPropGateway(session).platform_phone(user_id) == "79990000000"


def test_platform_phone_ignores_implausible_numbers(session, user_id):
    """На боевой платформе в users.phone встречаются значения длиной в одну
    цифру — подставлять такое продавцу как телефон нельзя."""
    session.execute(text("UPDATE users SET phone = 7 WHERE id_user = :id"), {"id": user_id})
    assert UserPropGateway(session).platform_phone(user_id) is None
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_user_prop_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.platform.user_prop_gateway'`

- [ ] **Step 3: Реализовать**

Создать `backend/app/platform/user_prop_gateway.py`:

```python
"""Anti-Corruption Layer к платформенному механизму расширяемых свойств
пользователя (`users_prop` + `users_prop_items_varchar|text`).

Тот же принцип, что у SellerGateway: GreenMarket не владеет этими таблицами и
не отображает их как ORM-модели. Если платформа однажды закроет прямой доступ к
БД и даст REST/gRPC, меняется только этот файл.

Свойство всегда резолвится по `var`, никогда по числовому `id_users_prop`: он
разный в боевой и локальной базе, и хардкод сломался бы молча — записал бы
значение в чужое свойство.
"""

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.profile.fields import VALUE_TYPE_TEXT, VALUE_TYPE_VARCHAR

_ITEMS_TABLE = {
    VALUE_TYPE_VARCHAR: "users_prop_items_varchar",
    VALUE_TYPE_TEXT: "users_prop_items_text",
}

# Границы правдоподобия для users.phone: колонка BIGINT, заполняется формой
# такси без строгой валидации — на проде встречаются значения от одной цифры.
# Подставлять такое продавцу как готовый телефон нельзя.
_PLAUSIBLE_PHONE_LENGTH = range(10, 16)


class UnknownPropError(LookupError):
    """Свойства с таким `var` нет в `users_prop`.

    Определения свойств заводит платформа (на проде — вручную, users_prop это
    её конфигурационная таблица), поэтому их отсутствие означает
    рассинхронизацию окружения, а не пользовательскую ошибку.
    """


class UserPropGateway:
    def __init__(self, session: Session):
        self.session = session

    def _resolve(self, prop_vars: list[str]) -> dict[str, tuple[int, int]]:
        """`var` → (`id_users_prop`, `value_type`) одним запросом."""
        if not prop_vars:
            return {}
        stmt = text(
            "SELECT var, id_users_prop, value_type FROM users_prop WHERE var IN :prop_vars"
        ).bindparams(bindparam("prop_vars", expanding=True))
        rows = self.session.execute(stmt, {"prop_vars": prop_vars}).all()
        resolved = {row[0]: (row[1], row[2]) for row in rows}
        missing = set(prop_vars) - resolved.keys()
        if missing:
            raise UnknownPropError(f"Свойства не заведены в users_prop: {', '.join(sorted(missing))}")
        return resolved

    def read(self, user_id: int, prop_vars: list[str]) -> dict[str, str]:
        """Значения свойств пользователя. Незаполненные в результат не попадают:
        `value` в таблицах значений объявлена NOT NULL, поэтому «пусто» — это
        отсутствие строки."""
        resolved = self._resolve(prop_vars)
        by_table: dict[str, list[int]] = {}
        prop_var_by_id = {}
        for prop_var, (prop_id, value_type) in resolved.items():
            by_table.setdefault(_ITEMS_TABLE[value_type], []).append(prop_id)
            prop_var_by_id[prop_id] = prop_var

        values: dict[str, str] = {}
        for table, prop_ids in by_table.items():
            stmt = text(
                f"SELECT id_users_prop, value FROM {table} "  # noqa: S608 — имя таблицы из _ITEMS_TABLE, не из запроса
                "WHERE id_user = :user_id AND id_users_prop IN :prop_ids"
            ).bindparams(bindparam("prop_ids", expanding=True))
            for prop_id, value in self.session.execute(stmt, {"user_id": user_id, "prop_ids": prop_ids}).all():
                values[prop_var_by_id[prop_id]] = value
        return values

    def write(self, user_id: int, prop_var: str, value: str) -> None:
        prop_id, value_type = self._resolve([prop_var])[prop_var]
        table = _ITEMS_TABLE[value_type]
        self.session.execute(
            text(
                f"INSERT INTO {table} (id_users_prop, id_user, value) "  # noqa: S608
                "VALUES (:prop_id, :user_id, :value) "
                "ON DUPLICATE KEY UPDATE value = VALUES(value)"
            ),
            {"prop_id": prop_id, "user_id": user_id, "value": value},
        )

    def clear(self, user_id: int, prop_var: str) -> None:
        """Очистка — DELETE, а не запись пустой строки: `value` NOT NULL, и
        пустая строка в карточке покупателя выглядела бы как заполненное поле."""
        prop_id, value_type = self._resolve([prop_var])[prop_var]
        table = _ITEMS_TABLE[value_type]
        self.session.execute(
            text(f"DELETE FROM {table} WHERE id_users_prop = :prop_id AND id_user = :user_id"),  # noqa: S608
            {"prop_id": prop_id, "user_id": user_id},
        )

    def platform_phone(self, user_id: int) -> str | None:
        """Учётный телефон платформы — только для предзаполнения профиля.

        GreenMarket в `users.phone` не пишет никогда: это учётное поле с флагом
        верификации, по нему в такси логинятся (договорённость с Валентином от
        06.08.2026). Правдоподобие проверяется, потому что колонка BIGINT без
        валидации на стороне платформы.
        """
        row = self.session.execute(
            text("SELECT phone FROM users WHERE id_user = :user_id"), {"user_id": user_id}
        ).first()
        if row is None or row[0] is None:
            return None
        phone = str(row[0])
        return phone if len(phone) in _PLAUSIBLE_PHONE_LENGTH else None
```

- [ ] **Step 4: Запустить тест**

Run: `cd backend && uv run pytest tests/test_user_prop_gateway.py -v`
Expected: PASS (11 тестов)

- [ ] **Step 5: Commit**

```bash
git add backend/app/platform/user_prop_gateway.py backend/tests/test_user_prop_gateway.py
git commit -m "feat: UserPropGateway — ACL к платформенным свойствам пользователя"
```

---

## Task 5: Модель и репозиторий журнала изменений

**Files:**
- Modify: `backend/app/infrastructure/models.py` (в конец файла)
- Create: `backend/app/infrastructure/repositories/seller_profile_change_repository.py`
- Test: `backend/tests/test_seller_profile_service.py` (создать — тесты `fields.py` из Task 3 живут отдельно, в `test_profile_fields.py`)

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_seller_profile_service.py`. Импорты — в начало файла, к уже имеющимся; тесты — в конец.

```python
import pytest
from sqlalchemy import text

from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)


@pytest.fixture
def seller(session) -> tuple[int, int]:
    """Возвращает (seller_id, user_id) нового продавца."""
    user_id = session.execute(
        text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для профиля"}
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return seller_id, user_id


def test_record_stores_author_and_role(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    repository.record(
        seller_id=seller_id,
        field="row",
        old_value=None,
        new_value="Ряд 3",
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()

    changes = repository.list_by_seller(seller_id)
    assert len(changes) == 1
    assert changes[0].field == "row"
    assert changes[0].old_value is None
    assert changes[0].new_value == "Ряд 3"
    assert changes[0].author_user_id == user_id
    assert changes[0].author_role == "SELLER"


def test_list_recent_returns_newest_first(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    for value in ("Ряд 1", "Ряд 2", "Ряд 3"):
        repository.record(
            seller_id=seller_id,
            field="row",
            old_value=None,
            new_value=value,
            author_user_id=user_id,
            author_role="ADMIN",
        )
    session.flush()

    recent = repository.list_recent(limit=2)
    assert [change.new_value for change in recent] == ["Ряд 3", "Ряд 2"]


def test_list_recent_respects_limit(session, seller):
    seller_id, user_id = seller
    repository = SellerProfileChangeRepository(session)
    for value in ("Ряд 1", "Ряд 2", "Ряд 3"):
        repository.record(
            seller_id=seller_id,
            field="row",
            old_value=None,
            new_value=value,
            author_user_id=user_id,
            author_role="ADMIN",
        )
    session.flush()

    assert len(repository.list_recent(limit=1)) == 1
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: FAIL — `ModuleNotFoundError: ...seller_profile_change_repository`

- [ ] **Step 3: Добавить ORM-модель**

Дописать в конец `backend/app/infrastructure/models.py`:

```python
class SellerProfileChange(Base):
    """Журнал изменений полей профиля продавца (миграция 015).

    Сами значения профиля живут в платформенных `users_prop_items_*`, где нет
    ни автора, ни времени — отсюда отдельная таблица GreenMarket. `author_role`
    хранится строкой ('SELLER'/'ADMIN'): по одному `author_user_id` роль не
    восстановить, администратор тоже пользователь платформы.
    """

    __tablename__ = "SellerProfileChange"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    author_user_id: Mapped[int] = mapped_column(Integer)
    author_role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Реализовать репозиторий**

Создать `backend/app/infrastructure/repositories/seller_profile_change_repository.py`:

```python
from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProfileChange


class SellerProfileChangeRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        seller_id: int,
        field: str,
        old_value: str | None,
        new_value: str | None,
        author_user_id: int,
        author_role: str,
    ) -> SellerProfileChange:
        change = SellerProfileChange(
            seller_id=seller_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            author_user_id=author_user_id,
            author_role=author_role,
        )
        self.session.add(change)
        return change

    def list_by_seller(self, seller_id: int) -> list[SellerProfileChange]:
        return (
            self.session.query(SellerProfileChange)
            .filter(SellerProfileChange.seller_id == seller_id)
            .order_by(SellerProfileChange.id.desc())
            .all()
        )

    def list_recent(self, *, limit: int) -> list[SellerProfileChange]:
        """Лента последних изменений для Admin Cabinet.

        Сортировка по `id`, а не по `created_at`: несколько полей, изменённых
        одним PUT, получают одинаковую метку времени с точностью до секунды, и
        порядок внутри такой пачки был бы неопределённым.
        """
        return (
            self.session.query(SellerProfileChange)
            .order_by(SellerProfileChange.id.desc())
            .limit(limit)
            .all()
        )
```

- [ ] **Step 5: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: PASS (7 тестов: 4 из Task 3 + 3 новых)

- [ ] **Step 6: Commit**

```bash
git add backend/app/infrastructure/models.py backend/app/infrastructure/repositories/seller_profile_change_repository.py backend/tests/test_seller_profile_service.py
git commit -m "feat: журнал изменений профиля продавца — модель и репозиторий"
```

---

## Task 6: SellerProfileService

**Files:**
- Create: `backend/app/profile/seller_profile_service.py`
- Test: `backend/tests/test_seller_profile_service.py` (дописать)

Сервис — единственное место, где «прочитать профиль» и «применить изменения с записью в журнал» описаны один раз для всех трёх потребителей.

**Проверка длины обязана жить здесь, а не полагаться на БД.** Для `short_description` БД не поймает превышение вообще: колонка `users_prop_items_text.value` держит 65535 символов, а ограничение 2000 — наше продуктовое. Для varchar-полей всё хуже, чем казалось при написании плана:

> **Проверено 06.08.2026 на обеих базах.** Локально `sql_mode = ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,...` — вставка 256 символов в `VARCHAR(255)` падает с `DataError (1406, "Data too long")`. **На проде `sql_mode` пустой** (`SELECT @@GLOBAL.sql_mode` → `''`, MySQL 8.0.46; в 8.0 это не дефолт, режим кто-то сознательно очистил). Без `STRICT_TRANS_TABLES` MySQL не падает, а **молча обрезает** значение. То есть на проде отсутствие проверки в `apply()` — это не «грубая пятисотка», а тихая потеря данных: продавец видит успешное сохранение и обрезанный телефон.
>
> Следствие шире профиля: локальная база и CI строгие, прод — нет, поэтому этот класс дефектов тестами не ловится нигде. Единственная защита — проверка длины на прикладном уровне. Менять `sql_mode` на проде нельзя: сервер общий с такси, конфигурация не наша зона.

То есть объявленный в `fields.py` `max_length` работает ровно настолько, насколько его проверяет `apply()`.

**Валидация идёт отдельным проходом до первой записи.** Если проверять длину внутри цикла записи, то `apply(seller_id, {"row": "Ряд 3", "short_description": "х" * 2001})` успеет записать `row` и завести журнальную запись, а потом упадёт — половина формы сохранена, продавец получил ошибку. Сначала нормализуем и проверяем все значения, только потом пишем.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_seller_profile_service.py`:

```python
from app.profile.errors import ProfileValidationError
from app.profile.seller_profile_service import SellerProfileService


def test_read_returns_all_fields_as_none_for_empty_profile(session, seller):
    seller_id, _ = seller
    profile = SellerProfileService(session).read(seller_id)
    assert profile == {
        "row": None,
        "place": None,
        "working_hours": None,
        "short_description": None,
        "phone": None,
        "whatsapp": None,
    }


def test_apply_writes_values_and_journal(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)

    changed = service.apply(
        seller_id,
        {"row": "Ряд 3", "phone": "+79990000000"},
        author_user_id=user_id,
        author_role="SELLER",
    )
    session.flush()

    assert changed == ["row", "phone"]
    profile = service.read(seller_id)
    assert profile["row"] == "Ряд 3"
    assert profile["phone"] == "+79990000000"

    journal = SellerProfileChangeRepository(session).list_by_seller(seller_id)
    assert {(change.field, change.old_value, change.new_value) for change in journal} == {
        ("row", None, "Ряд 3"),
        ("phone", None, "+79990000000"),
    }


def test_apply_records_old_value_on_overwrite(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"place": "Место 1"}, author_user_id=user_id, author_role="SELLER")
    service.apply(seller_id, {"place": "Место 2"}, author_user_id=user_id, author_role="ADMIN")
    session.flush()

    latest = SellerProfileChangeRepository(session).list_by_seller(seller_id)[0]
    assert (latest.field, latest.old_value, latest.new_value) == ("place", "Место 1", "Место 2")
    assert latest.author_role == "ADMIN"


def test_apply_ignores_unchanged_values(session, seller):
    """Сохранение формы без правок не должно засорять ленту админа."""
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"row": "Ряд 3"}, author_user_id=user_id, author_role="SELLER")
    changed = service.apply(seller_id, {"row": "Ряд 3"}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert changed == []
    assert len(SellerProfileChangeRepository(session).list_by_seller(seller_id)) == 1


def test_apply_clears_field_on_empty_string(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"working_hours": "9:00–18:00"}, author_user_id=user_id, author_role="SELLER")
    service.apply(seller_id, {"working_hours": ""}, author_user_id=user_id, author_role="SELLER")
    session.flush()

    assert service.read(seller_id)["working_hours"] is None
    latest = SellerProfileChangeRepository(session).list_by_seller(seller_id)[0]
    assert (latest.old_value, latest.new_value) == ("9:00–18:00", None)


def test_apply_strips_whitespace(session, seller):
    seller_id, user_id = seller
    service = SellerProfileService(session)
    service.apply(seller_id, {"row": "  Ряд 3  "}, author_user_id=user_id, author_role="SELLER")
    session.flush()
    assert service.read(seller_id)["row"] == "Ряд 3"


def test_apply_rejects_unknown_field(session, seller):
    seller_id, user_id = seller
    with pytest.raises(UnknownProfileFieldError):
        SellerProfileService(session).apply(
            seller_id, {"id_role": "4"}, author_user_id=user_id, author_role="SELLER"
        )


def test_apply_rejects_too_long_value(session, seller):
    seller_id, user_id = seller
    with pytest.raises(ValueError):
        SellerProfileService(session).apply(
            seller_id, {"row": "х" * 256}, author_user_id=user_id, author_role="SELLER"
        )


def test_read_suggests_platform_phone_when_own_is_empty(session, seller):
    seller_id, user_id = seller
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    assert SellerProfileService(session).read(seller_id)["phone"] is None
    assert SellerProfileService(session).suggested_phone(seller_id) == "79990000000"


def test_suggested_phone_is_none_when_own_value_exists(session, seller):
    seller_id, user_id = seller
    session.execute(
        text("UPDATE users SET phone = :phone WHERE id_user = :id"),
        {"phone": 79990000000, "id": user_id},
    )
    SellerProfileService(session).apply(
        seller_id, {"phone": "+79991112233"}, author_user_id=user_id, author_role="SELLER"
    )
    session.flush()
    assert SellerProfileService(session).suggested_phone(seller_id) is None
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: FAIL — `ModuleNotFoundError: ...seller_profile_service`

- [ ] **Step 3: Реализовать**

Создать `backend/app/profile/seller_profile_service.py`:

```python
"""Чтение и изменение профиля продавца.

Один сервис на трёх потребителей (книга продавца, Admin API, Catalog API) —
иначе правило «что считать изменением» и запись журнала пришлось бы повторять в
каждом.

Транзакцией сервис не управляет: `commit()` делает вызывающий эндпоинт, как и
во всём остальном коде (см. app/publication/publication_service.py).
"""

from sqlalchemy.orm import Session

from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.platform.seller_gateway import SellerGateway
from app.platform.user_prop_gateway import UserPropGateway
from app.profile.fields import PROFILE_FIELDS, field_by_name


class UnknownProfileFieldError(LookupError):
    """В запросе поле, которого нет в профиле."""


class SellerProfileService:
    def __init__(self, session: Session):
        self.session = session
        self.props = UserPropGateway(session)
        self.sellers = SellerGateway(session)
        self.journal = SellerProfileChangeRepository(session)

    def _user_id(self, seller_id: int) -> int | None:
        row = self.sellers.find_list_row(seller_id)
        return None if row is None else row.user_id

    def read(self, seller_id: int) -> dict[str, str | None]:
        """Профиль продавца. Незаполненные поля — `None`, а не отсутствующие
        ключи: потребителю (форма, карточка) удобнее одинаковый набор ключей."""
        user_id = self._user_id(seller_id)
        if user_id is None:
            return {field.name: None for field in PROFILE_FIELDS}
        stored = self.props.read(user_id, [field.prop_var for field in PROFILE_FIELDS])
        return {field.name: stored.get(field.prop_var) for field in PROFILE_FIELDS}

    def suggested_phone(self, seller_id: int) -> str | None:
        """Подсказка для незаполненного телефона — учётный номер платформы.

        Отдаётся отдельным полем ответа, а не подставляется в `phone`: пока
        продавец не сохранил номер сам, витринного телефона у него нет, и
        покупателю показывать учётный номер из такси мы не имеем права.
        Договорённость с Валентином 06.08.2026: предзаполняем, продавец
        подтверждает или переопределяет.
        """
        if self.read(seller_id)["phone"] is not None:
            return None
        user_id = self._user_id(seller_id)
        return None if user_id is None else self.props.platform_phone(user_id)

    def apply(
        self,
        seller_id: int,
        values: dict[str, str | None],
        *,
        author_user_id: int,
        author_role: str,
    ) -> list[str]:
        """Применяет изменения и возвращает имена реально изменившихся полей.

        Поля, которых нет в `values`, не трогаются — форма может присылать
        только то, что редактировала. Пустая строка и `None` означают очистку.
        """
        editable = {field.name for field in PROFILE_FIELDS}
        unknown = set(values) - editable
        if unknown:
            raise UnknownProfileFieldError(f"Неизвестные поля профиля: {', '.join(sorted(unknown))}")

        user_id = self._user_id(seller_id)
        if user_id is None:
            raise LookupError(f"Продавец {seller_id} не найден")

        current = self.read(seller_id)
        changed: list[str] = []

        for name, raw in values.items():
            field = field_by_name(name)
            new_value = (raw or "").strip() or None
            if new_value is not None and len(new_value) > field.max_length:
                raise ValueError(
                    f"Поле «{name}» длиннее допустимых {field.max_length} символов"
                )

            old_value = current[name]
            if new_value == old_value:
                continue

            if new_value is None:
                self.props.clear(user_id, field.prop_var)
            else:
                self.props.write(user_id, field.prop_var, new_value)

            self.journal.record(
                seller_id=seller_id,
                field=name,
                old_value=old_value,
                new_value=new_value,
                author_user_id=author_user_id,
                author_role=author_role,
            )
            changed.append(name)

        return changed
```

- [ ] **Step 4: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_seller_profile_service.py -v`
Expected: PASS (17 тестов)

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile/seller_profile_service.py backend/tests/test_seller_profile_service.py
git commit -m "feat: SellerProfileService — чтение профиля и применение изменений с журналом"
```

---

## Task 7: GET/PUT /api/v1/seller/profile

**Files:**
- Modify: `backend/app/api/v1/seller_schemas.py`, `backend/app/api/v1/seller.py`
- Test: `backend/tests/test_seller_profile_api.py`

Аутентификация — продавцовский `access_token`, как у `GET /api/v1/seller/catalog`: GET принимает его в query, PUT — в теле (так же, как `POST /api/v1/publications`). Резолвер берётся через `Depends(get_seller_access_resolver)`, чтобы тесты могли его подменить — см. `tests/test_publications_api.py`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_seller_profile_api.py`. Стиль повторяет `tests/test_seller_api.py`: `committing_session` (эндпоинт делает `commit()`, обычная фикстура `session` для этого не годится), локальные хелперы `override_session` / `override_seller_access`, клиент создаётся в самом тесте.

```python
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.publications import get_seller_access_resolver
from app.infrastructure.database import get_session
from app.main import app
from app.publication.seller_access import SellerAccess

VALID_TOKEN = "seller-profile-test-token"


def override_seller_access(seller_id: int, published_by: int) -> None:
    # published_by — это и есть платформенный users.id_user продавца
    # (см. app/publication/seller_access.py): поле названо по первому
    # потребителю, публикации, но хранит именно id пользователя.
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name="Пасека Ромашково")
    app.dependency_overrides[get_seller_access_resolver] = lambda: (
        lambda token: access if token == VALID_TOKEN else None
    )


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str, phone: int | None = None) -> tuple[int, int]:
    user_id = session.execute(
        text("INSERT INTO users (name, phone) VALUES (:name, :phone)"), {"name": name, "phone": phone}
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    return seller_id, user_id


def setup_client(committing_session, *, phone: int | None = None) -> tuple[TestClient, int]:
    seller_id, user_id = insert_seller(committing_session, name="Пасека Ромашково", phone=phone)
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    return TestClient(app), seller_id


def test_get_profile_returns_empty_fields_for_new_seller(committing_session):
    client, seller_id = setup_client(committing_session)

    response = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["name"] == "Пасека Ромашково"
    assert body["status"] == "ACTIVE"
    assert body["row"] is None
    assert body["phone"] is None
    assert body["suggested_phone"] is None


def test_get_profile_rejects_bad_token(committing_session):
    client, _ = setup_client(committing_session)

    response = client.get("/api/v1/seller/profile", params={"access_token": "nope"})

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_put_profile_saves_and_returns_changed_fields(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put(
        "/api/v1/seller/profile",
        json={"access_token": VALID_TOKEN, "row": "Ряд 3", "place": "Место 12"},
    )
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert sorted(response.json()["changed"]) == ["place", "row"]
    assert saved["row"] == "Ряд 3"
    assert saved["place"] == "Место 12"


def test_put_profile_leaves_omitted_fields_untouched(committing_session):
    client, _ = setup_client(committing_session)

    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "Ряд 3"})
    client.put("/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "place": "Место 12"})
    saved = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert saved["row"] == "Ряд 3"
    assert saved["place"] == "Место 12"


def test_put_profile_rejects_bad_token(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put("/api/v1/seller/profile", json={"access_token": "nope", "row": "Ряд 3"})

    app.dependency_overrides.clear()
    assert response.status_code == 403


def test_put_profile_rejects_too_long_value(committing_session):
    client, _ = setup_client(committing_session)

    response = client.put(
        "/api/v1/seller/profile", json={"access_token": VALID_TOKEN, "row": "х" * 256}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_profile_suggests_platform_phone(committing_session):
    client, _ = setup_client(committing_session, phone=79990000000)

    body = client.get("/api/v1/seller/profile", params={"access_token": VALID_TOKEN}).json()

    app.dependency_overrides.clear()
    assert body["phone"] is None
    assert body["suggested_phone"] == "79990000000"
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_seller_profile_api.py -v`
Expected: FAIL — 404 на `/api/v1/seller/profile`

- [ ] **Step 3: Добавить схемы**

Дописать в `backend/app/api/v1/seller_schemas.py`:

```python
class SellerProfileResponse(BaseModel):
    """Профиль продавца в терминах Seller_Profile.md, §4–5.

    `name` и `status` только для чтения: имя — учётное `users.name` платформы,
    статус меняется отдельными админскими операциями activate/deactivate.
    """

    seller_id: int
    name: str
    status: str
    row: str | None
    place: str | None
    working_hours: str | None
    short_description: str | None
    phone: str | None
    whatsapp: str | None
    suggested_phone: str | None


class SellerProfileUpdateRequest(BaseModel):
    """Правятся только переданные поля: отсутствие ключа — «не трогать»,
    пустая строка — «очистить». Поэтому у всех полей значение по умолчанию
    `None` и отличить «не прислали» от «прислали null» невозможно — для
    очистки форма присылает пустую строку.

    `extra="forbid"` добавлен после ревью Task 7. По умолчанию Pydantic молча
    отбрасывает лишние ключи ещё до сервиса, поэтому `UnknownProfileFieldError`
    через HTTP не поднимался вообще ничем: опечатка в имени поля возвращала
    200 и пустой `changed`. Единственный клиент — форма в книге продавца на
    Apps Script, где имена полей набиты руками, и «сохранилось» там
    неотличимо от «поле не то».
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str
    row: str | None = None
    place: str | None = None
    working_hours: str | None = None
    short_description: str | None = None
    phone: str | None = None
    whatsapp: str | None = None

    def changed_values(self) -> dict[str, str | None]:
        return self.model_dump(exclude={"access_token"}, exclude_unset=True)


class SellerProfileUpdateResponse(BaseModel):
    changed: list[str]
```

- [ ] **Step 4: Добавить эндпоинты**

Дописать в `backend/app/api/v1/seller.py` (импорты — к существующим):

```python
from app.api.v1.seller_schemas import (
    SellerActivationRequest,
    SellerActivationResponse,
    SellerProfileResponse,
    SellerProfileUpdateRequest,
    SellerProfileUpdateResponse,
    SellerStatusResponse,
)
from app.profile.errors import ProfileValidationError, SellerNotFoundError
from app.profile.seller_profile_service import SellerProfileService


def _profile_response(seller_id: int, *, session: Session) -> SellerProfileResponse | JSONResponse:
    """Одна строка `SellerListRow` вместо двух запросов: она несёт и `name`, и
    `is_active`, и `user_id`, который всё равно понадобится сервису. Имя
    продавца берётся отсюда, а не из токена, — иначе хелпером не смог бы
    воспользоваться админский аналог, у которого токена продавца нет."""
    seller = SellerGateway(session).find_list_row(seller_id)
    if seller is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    service = SellerProfileService(session)
    return SellerProfileResponse(
        seller_id=seller_id,
        name=seller.name,
        status="ACTIVE" if seller.is_active else "INACTIVE",
        suggested_phone=service.suggested_phone(seller_id),
        **service.read(seller_id),
    )


@router.get("/profile", response_model=SellerProfileResponse)
def get_seller_profile(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")
    return _profile_response(access.seller_id, session=session)


@router.put("/profile", response_model=SellerProfileUpdateResponse)
def update_seller_profile(
    request: SellerProfileUpdateRequest,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileUpdateResponse | JSONResponse:
    access = resolve_access(request.access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        changed = SellerProfileService(session).apply(
            access.seller_id,
            request.changed_values(),
            # `published_by` в SellerAccess — платформенный users.id_user
            # продавца; поле названо по первому потребителю (публикации), но
            # хранит именно идентификатор пользователя, который и нужен журналу.
            author_user_id=access.published_by,
            author_role="SELLER",
        )
    except SellerNotFoundError as exc:
        return error_response(404, "SELLER_NOT_FOUND", str(exc))
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return SellerProfileUpdateResponse(changed=changed)
```

- [ ] **Step 5: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_seller_profile_api.py -v`
Expected: PASS (7 тестов)

- [ ] **Step 6: Прогнать весь набор**

Run: `cd backend && uv run pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/seller.py backend/app/api/v1/seller_schemas.py backend/tests/test_seller_profile_api.py
git commit -m "feat: GET/PUT /api/v1/seller/profile"
```

---

## Task 8: Админская правка профиля и лента изменений

**Files:**
- Create: `backend/app/api/v1/admin_profile.py`
- Modify: `backend/app/api/v1/admin_schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_admin_profile_api.py`

Лента изменений — это то, что Валентин 06.08 принял вместо настоящих уведомлений: механизма push-уведомлений (почта, мессенджер) в системе нет вообще, админ смотрит ленту сам.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_admin_profile_api.py`. Стиль повторяет `tests/test_admin_sellers_api.py`: `committing_session` и **настоящий** админский токен, полученный через `POST /api/v1/admin/activate`, а не подмена `get_admin_access` — так тест заодно проверяет, что новые маршруты действительно закрыты аутентификацией.

```python
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin.admin_activation import issue_admin_activation_code
from app.infrastructure.database import get_session
from app.main import app


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def admin_headers(session, client, *, name: str) -> tuple[dict[str, str], int]:
    """Возвращает (заголовки, user_id администратора)."""
    user_id = insert_user(session, name=name)
    admin_id = session.execute(
        text("INSERT INTO Administrator (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid
    code = issue_admin_activation_code(admin_id, session=session)
    token = client.post("/api/v1/admin/activate", json={"activation_code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def insert_seller(session, *, name: str) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(
        text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}
    ).lastrowid


def test_admin_updates_seller_profile(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ профиля 1")
    seller_id = insert_seller(committing_session, name="Пасека Ромашково")

    response = client.put(
        f"/api/v1/admin/sellers/{seller_id}/profile",
        json={"row": "Ряд 7", "working_hours": "8:00–20:00"},
        headers=headers,
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert sorted(response.json()["changed"]) == ["row", "working_hours"]


def test_admin_update_of_missing_seller_is_404(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ профиля 2")

    response = client.put("/api/v1/admin/sellers/999999/profile", json={"row": "Ряд 7"}, headers=headers)

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"


def test_feed_shows_admin_as_author(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, admin_user_id = admin_headers(committing_session, client, name="Админ профиля 3")
    seller_id = insert_seller(committing_session, name="Пасека для ленты")

    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"place": "Место 5"}, headers=headers)
    feed = client.get("/api/v1/admin/profile-changes", headers=headers).json()

    app.dependency_overrides.clear()
    latest = feed["changes"][0]
    assert latest["seller_id"] == seller_id
    assert latest["field"] == "place"
    assert latest["new_value"] == "Место 5"
    assert latest["author_role"] == "ADMIN"
    assert latest["author_user_id"] == admin_user_id
    assert latest["seller_name"] == "Пасека для ленты"


def test_feed_is_newest_first(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ профиля 4")
    seller_id = insert_seller(committing_session, name="Пасека для порядка")

    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 2"}, headers=headers)
    feed = client.get("/api/v1/admin/profile-changes", headers=headers).json()

    app.dependency_overrides.clear()
    assert [change["new_value"] for change in feed["changes"][:2]] == ["Ряд 2", "Ряд 1"]


def test_feed_respects_limit(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    headers, _ = admin_headers(committing_session, client, name="Админ профиля 5")
    seller_id = insert_seller(committing_session, name="Пасека для лимита")

    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 1"}, headers=headers)
    client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 2"}, headers=headers)
    feed = client.get("/api/v1/admin/profile-changes", params={"limit": 1}, headers=headers).json()

    app.dependency_overrides.clear()
    assert len(feed["changes"]) == 1


def test_endpoints_require_admin_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)
    seller_id = insert_seller(committing_session, name="Пасека без токена")

    feed_response = client.get("/api/v1/admin/profile-changes")
    update_response = client.put(f"/api/v1/admin/sellers/{seller_id}/profile", json={"row": "Ряд 7"})

    app.dependency_overrides.clear()
    assert feed_response.status_code == 401
    assert update_response.status_code == 401
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_admin_profile_api.py -v`
Expected: FAIL — 404 на новых маршрутах

- [ ] **Step 3: Добавить схемы**

Дописать в `backend/app/api/v1/admin_schemas.py`:

```python
class AdminSellerProfileUpdateRequest(BaseModel):
    """Тот же набор полей, что у продавца, но без access_token — админ
    аутентифицируется заголовком Authorization (см. REST_API.md, Admin API).

    `extra="forbid"` — по той же причине, что и у `SellerProfileUpdateRequest`,
    и чтобы опечатка в имени поля не давала 422 продавцу и молчаливые 200
    администратору поверх одного и того же сервиса.
    """

    model_config = ConfigDict(extra="forbid")

    row: str | None = None
    place: str | None = None
    working_hours: str | None = None
    short_description: str | None = None
    phone: str | None = None
    whatsapp: str | None = None

    def changed_values(self) -> dict[str, str | None]:
        return self.model_dump(exclude_unset=True)


class AdminSellerProfileUpdateResponse(BaseModel):
    seller_id: int
    changed: list[str]


class SellerProfileChangeItem(BaseModel):
    id: int
    seller_id: int
    seller_name: str
    field: str
    old_value: str | None
    new_value: str | None
    author_user_id: int
    author_role: str
    created_at: datetime


class SellerProfileChangeFeedResponse(BaseModel):
    changes: list[SellerProfileChangeItem]
```

Если `datetime` ещё не импортирован в `admin_schemas.py` — добавить `from datetime import datetime` в начало файла.

- [ ] **Step 4: Реализовать роутер**

Создать `backend/app/api/v1/admin_profile.py`:

```python
"""Админская часть профиля продавца: правка полей и лента изменений.

Лента — сознательно pull, а не push: механизма уведомлений (почта, мессенджер)
в системе не существует, и Валентин 06.08.2026 принял ленту в Admin Cabinet как
достаточную для Stage 1.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess
from app.api.v1.admin import admin_access_denied, get_admin_access
from app.api.v1.admin_schemas import (
    AdminSellerProfileUpdateRequest,
    AdminSellerProfileUpdateResponse,
    SellerProfileChangeFeedResponse,
    SellerProfileChangeItem,
)
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session
from app.infrastructure.repositories.seller_profile_change_repository import (
    SellerProfileChangeRepository,
)
from app.platform.seller_gateway import SellerGateway
from app.profile.errors import ProfileValidationError, SellerNotFoundError
from app.profile.seller_profile_service import SellerProfileService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.put("/sellers/{seller_id}/profile", response_model=AdminSellerProfileUpdateResponse)
def update_seller_profile(
    seller_id: int,
    request: AdminSellerProfileUpdateRequest,
    session: Session = Depends(get_session),
    access: AdminAccess | None = Depends(get_admin_access),
) -> AdminSellerProfileUpdateResponse | JSONResponse:
    if access is None:
        return admin_access_denied()

    try:
        changed = SellerProfileService(session).apply(
            seller_id,
            request.changed_values(),
            author_user_id=access.user_id,
            author_role="ADMIN",
        )
    except SellerNotFoundError as exc:
        # В отличие от Seller API, здесь seller_id приходит из пути, а не из
        # токена, поэтому несуществующий продавец — реальная ситуация, а не
        # недостижимая ветка.
        return error_response(404, "SELLER_NOT_FOUND", str(exc))
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return AdminSellerProfileUpdateResponse(seller_id=seller_id, changed=changed)


@router.get("/profile-changes", response_model=SellerProfileChangeFeedResponse)
def list_profile_changes(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    access: AdminAccess | None = Depends(get_admin_access),
) -> SellerProfileChangeFeedResponse | JSONResponse:
    if access is None:
        return admin_access_denied()

    changes = SellerProfileChangeRepository(session).list_recent(limit=limit)
    names = SellerGateway(session).list_seller_names([change.seller_id for change in changes])

    return SellerProfileChangeFeedResponse(
        changes=[
            SellerProfileChangeItem(
                id=change.id,
                seller_id=change.seller_id,
                seller_name=names.get(change.seller_id, ""),
                field=change.field,
                old_value=change.old_value,
                new_value=change.new_value,
                author_user_id=change.author_user_id,
                author_role=change.author_role,
                created_at=change.created_at,
            )
            for change in changes
        ]
    )
```

- [ ] **Step 5: Подключить роутер**

В `backend/app/main.py` добавить импорт после строки `from app.api.v1.admin_moderation import router as admin_moderation_router`:

```python
from app.api.v1.admin_profile import router as admin_profile_router
```

и подключение после строки `app.include_router(admin_moderation_router)`:

```python
app.include_router(admin_profile_router)
```

- [ ] **Step 6: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_admin_profile_api.py -v`
Expected: PASS (6 тестов)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/admin_profile.py backend/app/api/v1/admin_schemas.py backend/app/main.py backend/tests/test_admin_profile_api.py
git commit -m "feat: админская правка профиля продавца и лента изменений"
```

---

## Task 9: Карточка продавца покупателю

**Files:**
- Modify: `backend/app/application/catalog_use_case.py`, `backend/app/api/v1/catalog_schemas.py`, `backend/app/api/v1/catalog.py`
- Test: `backend/tests/test_catalog_api.py` (дописать)

Отдельный эндпоинт, а не расширение `SellerOfferItem`: карточка продавца — самостоятельный экран Customer UI (`Seller_Profile.md`, §9), а раздувать каждое предложение в списке товара шестью полями профиля незачем. Профили со `status ≠ ACTIVE` покупателю не отдаются (§9, последняя строка) — то же правило, по которому деактивированный продавец исчезает из каталога.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_catalog_api.py`. Файл не использует фикстуру-клиент: каждый тест берёт `committing_session`, вызывает локальный хелпер `override_session(...)` и создаёт `TestClient(app)` сам — новые тесты повторяют этот же стиль, чтобы файл остался однородным.

```python
def insert_seller_with_user(session, *, name: str, is_active: bool = True, phone: int | None = None) -> tuple[int, int]:
    """Возвращает (seller_id, user_id). Отличается от insert_active_seller тем,
    что отдаёт user_id (нужен как автор изменений профиля) и умеет создавать
    неактивного продавца и заполнять учётный телефон платформы."""
    user_id = session.execute(
        text("INSERT INTO users (name, phone) VALUES (:name, :phone)"), {"name": name, "phone": phone}
    ).lastrowid
    seller_id = session.execute(
        text("INSERT INTO Seller (user_id, is_active) VALUES (:user_id, :is_active)"),
        {"user_id": user_id, "is_active": is_active},
    ).lastrowid
    return seller_id, user_id


def test_seller_card_returns_profile_fields(committing_session):
    seller_id, user_id = insert_seller_with_user(committing_session, name="Пасека Ромашково")
    SellerProfileService(committing_session).apply(
        seller_id,
        {"row": "Ряд 3", "place": "Место 12", "phone": "+79990000000", "working_hours": "8:00–18:00"},
        author_user_id=user_id,
        author_role="SELLER",
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["name"] == "Пасека Ромашково"
    assert body["row"] == "Ряд 3"
    assert body["place"] == "Место 12"
    assert body["phone"] == "+79990000000"
    assert body["working_hours"] == "8:00–18:00"
    assert body["short_description"] is None


def test_seller_card_hides_inactive_seller(committing_session):
    seller_id, _ = insert_seller_with_user(committing_session, name="Скрытый продавец", is_active=False)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_seller_card_404_for_missing_seller(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/sellers/999999")

    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_seller_card_never_exposes_platform_phone(committing_session):
    """Учётный телефон платформы — не витринный контакт: пока продавец не
    сохранил свой, покупателю показывать нечего."""
    seller_id, _ = insert_seller_with_user(
        committing_session, name="Без телефона в профиле", phone=79990000000
    )
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/sellers/{seller_id}")

    app.dependency_overrides.clear()
    assert response.json()["phone"] is None
```

`from fastapi.testclient import TestClient`, `from sqlalchemy import text` и `from app.main import app` в файле уже есть. Добавить в начало файла только `from app.profile.seller_profile_service import SellerProfileService`.

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_catalog_api.py -v -k seller_card`
Expected: FAIL — 404 на `/api/v1/catalog/sellers/{id}`

- [ ] **Step 3: Добавить метод в use case**

Дописать в класс `CatalogUseCase` (`backend/app/application/catalog_use_case.py`):

```python
    def get_seller_card(self, seller_id: int) -> dict | None:
        """Карточка продавца для покупателя (Seller_Profile.md, §9).

        Деактивированный продавец покупателю не показывается — то же правило,
        по которому его товары исчезают из каталога.
        """
        row = self.seller_gateway.find_list_row(seller_id)
        if row is None or not row.is_active:
            return None
        profile = SellerProfileService(self.session).read(seller_id)
        return {"seller_id": row.seller_id, "name": row.name, **profile}
```

Добавить импорт `from app.profile.seller_profile_service import SellerProfileService` в начало файла. `self.session` в `CatalogUseCase.__init__` уже есть — заводить ничего не нужно.

- [ ] **Step 4: Добавить схему**

Дописать в `backend/app/api/v1/catalog_schemas.py`:

```python
class SellerCardResponse(BaseModel):
    """Карточка продавца в Customer UI. `status` не отдаётся: неактивный
    продавец покупателю просто не существует (404)."""

    seller_id: int
    name: str
    row: str | None
    place: str | None
    working_hours: str | None
    short_description: str | None
    phone: str | None
    whatsapp: str | None
```

- [ ] **Step 5: Добавить эндпоинт**

Дописать в `backend/app/api/v1/catalog.py` (и добавить `SellerCardResponse` в существующий импорт из `catalog_schemas`):

```python
@router.get("/sellers/{seller_id}", response_model=SellerCardResponse)
def get_seller_card(seller_id: int, session: Session = Depends(get_session)) -> SellerCardResponse | JSONResponse:
    card = CatalogUseCase(session).get_seller_card(seller_id)
    if card is None:
        return _not_found(f"Продавец {seller_id} не найден или недоступен")
    return SellerCardResponse(**card)
```

- [ ] **Step 6: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_catalog_api.py -v`
Expected: PASS

- [ ] **Step 7: Прогнать весь набор**

Run: `cd backend && uv run pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/application/catalog_use_case.py backend/app/api/v1/catalog_schemas.py backend/app/api/v1/catalog.py backend/tests/test_catalog_api.py
git commit -m "feat: GET /api/v1/catalog/sellers/{id} — карточка продавца покупателю"
```

---

## Task 10: Документация

**Files:**
- Modify: `docs/04-services/REST_API.md`, `docs/02-domain/Seller_Profile.md`, `docs/03-database/Database_Migrations.md`

- [ ] **Step 0: Внести миграцию 015 в реестр**

В `docs/03-database/Database_Migrations.md` две вещи:

- цепочка порядка применения (строка ~29, вида `001 → 002 → … → 014`) — дописать `→ 015`;
- таблица со списком файлов миграций (строки ~62–63) — добавить строку по образцу соседних:

```markdown
| `015_create_seller_profile_change.sql` | создание таблицы `SellerProfileChange` (журнал изменений полей профиля продавца) |
```

Точную формулировку колонок брать по образцу строк про `013_create_administrator.sql` и `014_fix_moderation_status_invariant.sql` — структура таблицы может отличаться от приведённой здесь.

- [ ] **Step 0b: Внести `SellerProfileChange` в нормативные разделы Coding_Standard.md**

В `docs/03-database/Coding_Standard.md`:

- раздел «Исторические таблицы» перечисляет как append-only только `CatalogPublication` — добавить `SellerProfileChange` (журнал изменений профиля тоже пишется только на вставку, записи не редактируются и не удаляются);
- таблица «Владение данными» не содержит `SellerProfileChange` — добавить строку: владелец — Seller Profile (запись только через `SellerProfileService`), остальные компоненты пишут в неё запрещено.

Если формулировки разделов не позволяют вписать это без искажения смысла — не выдумывать, сообщить и оставить как есть.

- [ ] **Step 1: Описать эндпоинты в REST_API.md**

В разделе **Catalog API** дописать после строки про `GET /api/v1/catalog/products/{id}`:

```markdown
- `GET /api/v1/catalog/sellers/{id}` — карточка продавца: `{"seller_id": int, "name": str, "row": str|null, "place": str|null, "working_hours": str|null, "short_description": str|null, "phone": str|null, "whatsapp": str|null}`. Состав — `Seller_Profile.md`, §9. Деактивированный или несуществующий продавец — `404` `NOT_FOUND`: покупателю неактивный продавец не показывается (§9), и различать эти два случая незачем. Учётный телефон платформы (`users.phone`) здесь никогда не появляется — отдаётся только то, что продавец сохранил сам.
```

В разделе **Seller API** дописать после `GET /api/v1/seller/catalog`:

```markdown
- `GET /api/v1/seller/profile?access_token=...` — профиль продавца для книги продавца: `{"seller_id": int, "name": str, "status": "ACTIVE"|"INACTIVE", "row": str|null, "place": str|null, "working_hours": str|null, "short_description": str|null, "phone": str|null, "whatsapp": str|null, "suggested_phone": str|null}`. `name` и `status` только для чтения: имя — учётное `users.name` платформы, статус меняется админскими `PUT /api/v1/admin/sellers/{id}/activate|deactivate`. `suggested_phone` — учётный телефон платформы, предлагаемый как заготовка, пока продавец не сохранил свой; в карточку покупателю он не попадает и в `users` ничего не пишется (договорённость от 06.08.2026: `users.phone`/`users.wa` — учётные поля платформы с флагами верификации, витринный контакт продавца хранится отдельно).
- `PUT /api/v1/seller/profile` — сохранение профиля. Тело `{"access_token": str, "row": str|null, ...}`; правятся только переданные ключи, пустая строка очищает поле. Ответ — `{"changed": [str]}`, список реально изменившихся полей (сохранение формы без правок возвращает пустой список и не пишет ничего в журнал). `403` `SELLER_ACCESS_DENIED`, `422` `VALIDATION_ERROR` при неизвестном поле или превышении длины.
```

В разделе **Admin API** дописать после эндпоинтов `activate`/`deactivate`:

```markdown
- `PUT /api/v1/admin/sellers/{id}/profile` — правка профиля продавца администратором. Тело — те же поля, что у `PUT /api/v1/seller/profile`, без `access_token` (админ аутентифицируется заголовком). Ответ — `{"seller_id": int, "changed": [str]}`. В журнале автором записывается администратор. `404` `SELLER_NOT_FOUND`.
- `GET /api/v1/admin/profile-changes?limit=` — лента последних изменений профилей, новые первыми (`limit` по умолчанию 50, максимум 200). Ответ — `{"changes": [{"id": int, "seller_id": int, "seller_name": str, "field": str, "old_value": str|null, "new_value": str|null, "author_user_id": int, "author_role": "SELLER"|"ADMIN", "created_at": datetime}]}`. Это осознанно pull, а не push: механизма уведомлений (почта, мессенджер) в системе нет, и лента принята коллегой как достаточная для Stage 1.
```

- [ ] **Step 2: Описать хранение в Seller_Profile.md**

Дописать новый раздел перед разделом «11. Не входит в PR»:

```markdown
## 10a. Физическое хранение полей (Stage 1)

Раздел добавлен по итогам решения от 06.08.2026 и описывает реализацию, а не доменную модель.

Значения редактируемых полей хранятся не собственной таблицей GreenMarket, а платформенным механизмом расширяемых свойств пользователя (`users_prop` + `users_prop_items_varchar|text`). Соответствие:

| Поле профиля | Свойство платформы | Тип значения |
|---|---|---|
| `row` | `gm_seller_row` | varchar |
| `place` | `gm_seller_place` | varchar |
| `workingHours` | `gm_seller_working_hours` | varchar |
| `shortDescription` | `gm_seller_short_description` | text |
| `phone` | `gm_seller_phone` | varchar |
| `whatsapp` | `gm_seller_whatsapp` | varchar |

`name` берётся из `users.name`, `status` — из `Seller.is_active`; ни то, ни другое через профиль не редактируется.

`phone` и `whatsapp` намеренно **не** пишутся в `users.phone` / `users.wa`: это учётные поля платформы с флагами верификации, по телефону в такси выполняется вход. Витринный контакт продавца — то, что видит покупатель, — может отличаться от учётного номера и должен быть публично видимым, а у колонок `users` управления видимостью нет. Учётный телефон используется только как заготовка при первом заполнении профиля (`suggested_phone` в Seller API), запись в `users` не производится ни при каких условиях.

Изменения полей фиксируются в журнале `SellerProfileChange` (миграция 015): в таблицах значений платформы нет ни автора, ни времени изменения.
```

- [ ] **Step 3: Проверить, что ссылки на файлы в документации не битые**

```bash
grep -n "015_create_seller_profile_change" docs/04-services/REST_API.md docs/02-domain/Seller_Profile.md database/migrations/015_create_seller_profile_change.sql
```

Expected: миграция существует; упоминания в документации соответствуют реальному имени файла.

- [ ] **Step 4: Commit**

```bash
git add docs/04-services/REST_API.md docs/02-domain/Seller_Profile.md
git commit -m "docs: профиль продавца в REST_API.md и Seller_Profile.md"
```

---

## Task 11: Финальная проверка

- [ ] **Step 1: Полный прогон тестов**

Run: `cd backend && uv run pytest tests/ -q`
Expected: PASS, ноль упавших.

- [ ] **Step 2: Проверить, что в git не попало лишнее**

```bash
git status --short
```

Expected: чисто. Ничего из `kwork/`, никаких `*.zip`.

- [ ] **Step 3: Проверить, что приложение поднимается**

```bash
cd backend && uv run python -c "from app.main import app; print(sorted({route.path for route in app.routes if 'profile' in route.path}))"
```

Expected: `['/api/v1/admin/profile-changes', '/api/v1/admin/sellers/{seller_id}/profile', '/api/v1/seller/profile']`

- [ ] **Step 4: Убедиться, что в коде нет хардкода id свойств**

```bash
grep -rn "id_users_prop\s*=\s*[0-9]" backend/app
```

Expected: пусто.

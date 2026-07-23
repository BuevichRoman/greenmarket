# Seller Activation Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить статический `SELLER_ACCESS_TOKENS` (`.env`) на DB-backed `access_token`, выдаваемый через одноразовый `activation_code` при первой привязке персональной копии Google Sheets продавца — см. [design doc](../specs/2026-07-23-seller-activation-auth-design.md).

**Architecture:** Миграция добавляет `access_token`/`activation_code`/`activation_code_expires_at`/`spreadsheet_id`/`activated_at` в `Seller`. Новый endpoint `POST /api/v1/seller/activate` обменивает `activation_code` на постоянный `access_token` (одноразово). `resolve_seller_access()` переезжает с парсинга `.env`-JSON на DB-запрос через `SellerGateway` (тот же Anti-Corruption Layer паттерн, что и остальные операции над `Seller`). Apps Script переиспользует существующую точку `getOrPromptAccessToken()` — вместо запроса сырого токена она теперь запрашивает `activation_code` и обменивает его на токен через новый endpoint.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (raw SQL для платформенных таблиц, ORM — для GreenMarket-таблиц), MySQL 8.0.36, pytest, Google Apps Script.

---

## Перед стартом

Прочитать design doc целиком: [`docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md`](../specs/2026-07-23-seller-activation-auth-design.md). Все backend-пути ниже — относительно `backend/`, если не сказано иное.

**Одно сознательное отличие от design doc** (обнаружено при разведке кода, до старта реализации): design описывает `onOpen()`, показывающий отдельный пункт меню «Активировать доступ» вместо «Открыть карточку»/«Добавить товар», пока токена нет. Разведка `apps_script/product_card/Code.gs` нашла уже существующую единую точку входа `getOrPromptAccessToken()` (строка 146) — её сейчас вызывают `uploadPhoto()`/`getPhotoUrls()` перед любым обращением к API, и она уже прячет запрос токена, если он есть в `PropertiesService`. Task 9 переиспользует именно её (меняя, ЧТО она запрашивает — `activation_code` вместо сырого `access_token` — и добавляя обмен на бэкенде), вместо добавления отдельного условного пункта меню. Результат для продавца тот же (секрет вводится один раз, дальше прозрачно), реализация проще и не дублирует существующий механизм.

Бонус той же разведки: `handleApiResponse()` (строка 166) уже удаляет `ACCESS_TOKEN_PROPERTY` при ответе `403` — значит отзыв доступа (`Seller.is_active = FALSE`) уже автоматически приведёт к тому, что при следующем обращении Apps Script снова запросит активацию. Ничего дополнительно чинить для этого не нужно.

---

### Task 1: Миграция `Seller` — activation/access-поля

**Files:**
- Create: `database/migrations/011_alter_seller_add_activation.sql`

- [ ] **Step 1: Написать миграцию**

```sql
-- Источник: docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md
-- Переносит access_token из SELLER_ACCESS_TOKENS (.env) в БД + добавляет
-- одноразовый activation_code для первичной привязки персональной копии
-- Google Sheets продавца к его Seller.

ALTER TABLE Seller
    ADD COLUMN access_token               VARCHAR(64)  NULL COMMENT 'Постоянный рабочий токен продавца (заменяет SELLER_ACCESS_TOKENS)',
    ADD COLUMN activation_code            VARCHAR(32)  NULL COMMENT 'Одноразовый код первичной привязки, NULL после использования',
    ADD COLUMN activation_code_expires_at DATETIME     NULL COMMENT 'TTL кода активации',
    ADD COLUMN spreadsheet_id             VARCHAR(100) NULL COMMENT 'ID персональной копии Google Sheets продавца (справочно)',
    ADD COLUMN activated_at               DATETIME     NULL COMMENT 'Когда код активации был использован',
    ADD UNIQUE INDEX uk_Seller_access_token (access_token),
    ADD UNIQUE INDEX uk_Seller_activation_code (activation_code);
```

- [ ] **Step 2: Применить миграцию локально**

Run: `mysql -u root -p greenmarket < ../database/migrations/011_alter_seller_add_activation.sql`
Expected: без ошибок (`Seller` уже существует из миграции 003).

- [ ] **Step 3: Проверить структуру таблицы**

Run: `mysql -u root -p greenmarket -e "DESCRIBE Seller;"`
Expected: 5 новых строк — `access_token`, `activation_code`, `activation_code_expires_at`, `spreadsheet_id`, `activated_at`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/011_alter_seller_add_activation.sql
git commit -m "GreenMarket: миграция 011 — Seller.access_token/activation_code (замена SELLER_ACCESS_TOKENS)"
```

**Про CI и стаб `users`:** `.github/workflows/backend-ci.yml` применяет миграции по маске `../database/migrations/*.sql` (уже так с прошлой миграции, глоб не редактировался с 17.07) — новый файл `011_...sql` подхватится автоматически, править workflow не нужно. `tests/fixtures/platform_stub.sql` стабит только `users` — эта миграция трогает `Seller`, а не `users`, так что и стаб редактировать не нужно.

---

### Task 2: `SellerGateway` — методы активации

**Files:**
- Modify: `app/platform/seller_gateway.py`
- Test: `tests/test_seller_gateway.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_seller_gateway.py`:

```python
from datetime import datetime, timedelta, timezone


def test_set_activation_code_and_find_by_activation_code(session):
    seller_id = insert_seller(session, name="Продавец для кода активации", publication_key=None, catalog_hash=None)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    gateway = SellerGateway(session)

    gateway.set_activation_code(seller_id, activation_code="abc12345", expires_at=expires_at)
    lookup = gateway.find_by_activation_code("abc12345")

    assert lookup is not None
    assert lookup.seller_id == seller_id
    assert lookup.activation_code_expires_at == expires_at


def test_find_by_activation_code_returns_none_for_unknown_code(session):
    assert SellerGateway(session).find_by_activation_code("does-not-exist") is None


def test_set_access_token_clears_activation_code_and_sets_fields(session):
    seller_id = insert_seller(session, name="Продавец для access_token", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_activation_code(
        seller_id, activation_code="code-1", expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    )

    gateway.set_access_token(seller_id, access_token="tok-xyz", spreadsheet_id="sheet-abc")

    assert gateway.find_by_activation_code("code-1") is None  # код одноразовый, обнулён
    access = gateway.find_by_access_token("tok-xyz")
    assert access is not None
    assert access.seller_id == seller_id


def test_find_by_access_token_returns_none_for_unknown_token(session):
    assert SellerGateway(session).find_by_access_token("does-not-exist") is None


def test_find_by_access_token_returns_none_for_inactive_seller(session):
    seller_id = insert_seller(session, name="Неактивный продавец с токеном", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_access_token(seller_id, access_token="tok-inactive", spreadsheet_id="sheet-x")
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    assert gateway.find_by_access_token("tok-inactive") is None


def test_find_by_access_token_returns_seller_name_from_users(session):
    seller_id = insert_seller(session, name="Ферма Токеновая", publication_key=None, catalog_hash=None)
    gateway = SellerGateway(session)
    gateway.set_access_token(seller_id, access_token="tok-name", spreadsheet_id="sheet-n")

    access = gateway.find_by_access_token("tok-name")

    assert access.name == "Ферма Токеновая"
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `uv run pytest tests/test_seller_gateway.py -v`
Expected: FAIL — `AttributeError: 'SellerGateway' object has no attribute 'set_activation_code'` (и аналогично для остальных новых методов).

- [ ] **Step 3: Добавить dataclasses и методы в `SellerGateway`**

В `app/platform/seller_gateway.py`, добавить импорт `datetime` (первая строка файла: `from dataclasses import dataclass` → добавить строку выше `from datetime import datetime`):

```python
from datetime import datetime
from dataclasses import dataclass
```

После `SellerStatus`, добавить ещё два dataclass:

```python
@dataclass(frozen=True)
class ActivationLookup:
    seller_id: int
    activation_code_expires_at: datetime | None


@dataclass(frozen=True)
class SellerAccessRow:
    seller_id: int
    user_id: int
    name: str
```

В конец класса `SellerGateway` (после `list_active_seller_ids`), добавить 4 метода:

```python
    def find_by_activation_code(self, activation_code: str) -> ActivationLookup | None:
        row = self.session.execute(
            text("SELECT id, activation_code_expires_at FROM Seller WHERE activation_code = :code"),
            {"code": activation_code},
        ).first()
        if row is None:
            return None
        return ActivationLookup(seller_id=row[0], activation_code_expires_at=row[1])

    def set_activation_code(self, seller_id: int, *, activation_code: str, expires_at: datetime) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET activation_code = :code, activation_code_expires_at = :expires_at "
                "WHERE id = :seller_id"
            ),
            {"code": activation_code, "expires_at": expires_at, "seller_id": seller_id},
        )

    def set_access_token(self, seller_id: int, *, access_token: str, spreadsheet_id: str) -> None:
        self.session.execute(
            text(
                "UPDATE Seller SET access_token = :access_token, spreadsheet_id = :spreadsheet_id, "
                "activated_at = NOW(), activation_code = NULL, activation_code_expires_at = NULL "
                "WHERE id = :seller_id"
            ),
            {"access_token": access_token, "spreadsheet_id": spreadsheet_id, "seller_id": seller_id},
        )

    def find_by_access_token(self, access_token: str) -> SellerAccessRow | None:
        row = self.session.execute(
            text(
                "SELECT s.id, s.user_id, u.name FROM Seller s "
                "JOIN users u ON u.id_user = s.user_id "
                "WHERE s.access_token = :token AND s.is_active = TRUE"
            ),
            {"token": access_token},
        ).first()
        if row is None:
            return None
        return SellerAccessRow(seller_id=row[0], user_id=row[1], name=row[2])
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/test_seller_gateway.py -v`
Expected: PASS (все, включая новые 6).

- [ ] **Step 5: Commit**

```bash
git add app/platform/seller_gateway.py tests/test_seller_gateway.py
git commit -m "GreenMarket: SellerGateway — методы активации (activation_code/access_token)"
```

---

### Task 3: `seller_activation.py` — выдача и обмен кода

**Files:**
- Create: `app/publication/seller_activation.py`
- Test: `tests/test_seller_activation.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_seller_activation.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.publication.seller_activation import activate_seller, issue_activation_code


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def test_issue_activation_code_sets_code_and_future_expiry(session):
    seller_id = insert_seller(session, name="Продавец для выдачи кода")

    code = issue_activation_code(seller_id, session=session)

    assert code is not None
    row = session.execute(
        text("SELECT activation_code, activation_code_expires_at FROM Seller WHERE id = :id"), {"id": seller_id}
    ).first()
    assert row[0] == code
    assert row[1] > datetime.now(timezone.utc).replace(tzinfo=None)


def test_issue_activation_code_returns_none_for_missing_seller(session):
    assert issue_activation_code(999_999, session=session) is None


def test_issue_activation_code_overwrites_previous_code(session):
    seller_id = insert_seller(session, name="Продавец для перевыпуска кода")
    first_code = issue_activation_code(seller_id, session=session)

    second_code = issue_activation_code(seller_id, session=session)

    assert second_code != first_code
    row = session.execute(text("SELECT activation_code FROM Seller WHERE id = :id"), {"id": seller_id}).first()
    assert row[0] == second_code


def test_activate_seller_returns_access_token_for_valid_code(session):
    seller_id = insert_seller(session, name="Продавец для активации")
    code = issue_activation_code(seller_id, session=session)

    access_token = activate_seller(code, spreadsheet_id="sheet-123", session=session)

    assert access_token is not None
    row = session.execute(
        text("SELECT access_token, spreadsheet_id, activation_code FROM Seller WHERE id = :id"), {"id": seller_id}
    ).first()
    assert row[0] == access_token
    assert row[1] == "sheet-123"
    assert row[2] is None


def test_activate_seller_returns_none_for_unknown_code(session):
    assert activate_seller("does-not-exist", spreadsheet_id="sheet-x", session=session) is None


def test_activate_seller_returns_none_for_expired_code(session):
    seller_id = insert_seller(session, name="Продавец с просроченным кодом")
    expired_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.execute(
        text("UPDATE Seller SET activation_code = :code, activation_code_expires_at = :expires_at WHERE id = :id"),
        {"code": "expired-code", "expires_at": expired_at, "id": seller_id},
    )

    assert activate_seller("expired-code", spreadsheet_id="sheet-y", session=session) is None


def test_activate_seller_code_is_single_use(session):
    seller_id = insert_seller(session, name="Продавец одноразовый код")
    code = issue_activation_code(seller_id, session=session)
    first_token = activate_seller(code, spreadsheet_id="sheet-1", session=session)
    assert first_token is not None

    second_token = activate_seller(code, spreadsheet_id="sheet-2", session=session)

    assert second_token is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `uv run pytest tests/test_seller_activation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.publication.seller_activation'`.

- [ ] **Step 3: Реализовать `seller_activation.py`**

```python
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.platform.seller_gateway import SellerGateway

ACTIVATION_CODE_TTL_DAYS = 7


def issue_activation_code(seller_id: int, *, session: Session, ttl_days: int = ACTIVATION_CODE_TTL_DAYS) -> str | None:
    """Админская операция: генерирует новый одноразовый activation_code для
    существующего Seller, затирая предыдущий (если был). Не коммитит —
    вызывающий код (CLI-скрипт) отвечает за commit()."""
    gateway = SellerGateway(session)
    if gateway.get_status(seller_id) is None:
        return None

    code = secrets.token_hex(4)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=ttl_days)
    gateway.set_activation_code(seller_id, activation_code=code, expires_at=expires_at)
    return code


def activate_seller(activation_code: str, *, spreadsheet_id: str, session: Session) -> str | None:
    """Резолвит одноразовый activation_code в постоянный access_token и
    привязывает конкретную копию Google Sheets продавца (spreadsheet_id).
    Не коммитит — вызывающий код (API-эндпоинт) отвечает за commit()."""
    gateway = SellerGateway(session)
    lookup = gateway.find_by_activation_code(activation_code)
    if lookup is None:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if lookup.activation_code_expires_at is None or lookup.activation_code_expires_at < now:
        return None

    access_token = secrets.token_urlsafe(32)
    gateway.set_access_token(lookup.seller_id, access_token=access_token, spreadsheet_id=spreadsheet_id)
    return access_token
```

**Важно про типы дат:** `datetime.now(timezone.utc).replace(tzinfo=None)` — намеренно naive. `pymysql` возвращает значения `DATETIME`-колонок как naive `datetime` (MySQL не хранит timezone) — сравнение aware-с-naive кинуло бы `TypeError`. Везде, где сравниваем «сейчас» с прочитанным из БД значением, используем одинаково naive UTC.

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/test_seller_activation.py -v`
Expected: PASS (все 7).

- [ ] **Step 5: Commit**

```bash
git add app/publication/seller_activation.py tests/test_seller_activation.py
git commit -m "GreenMarket: seller_activation.py — issue_activation_code/activate_seller"
```

---

### Task 4: `resolve_seller_access()` — переезд на БД

**Files:**
- Modify: `app/publication/seller_access.py`
- Test: `tests/test_seller_access.py` (полностью переписывается)

- [ ] **Step 1: Переписать тесты (падающие с текущей реализацией)**

Заменить всё содержимое `tests/test_seller_access.py`:

```python
from sqlalchemy import text

from app.publication.seller_access import resolve_seller_access


def insert_seller(session, *, name: str, access_token: str | None = None) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    seller_id = session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid
    if access_token is not None:
        session.execute(
            text("UPDATE Seller SET access_token = :token, is_active = TRUE WHERE id = :id"),
            {"token": access_token, "id": seller_id},
        )
    return seller_id


def test_valid_token_resolves_to_seller_access(session):
    seller_id = insert_seller(session, name="Ферма Ромашково", access_token="tok-abc")

    access = resolve_seller_access("tok-abc", session)

    assert access is not None
    assert access.seller_id == seller_id
    assert access.name == "Ферма Ромашково"


def test_unknown_token_resolves_to_none(session):
    insert_seller(session, name="Ферма Ромашково", access_token="tok-abc")

    assert resolve_seller_access("tok-does-not-exist", session) is None


def test_inactive_seller_resolves_to_none(session):
    seller_id = insert_seller(session, name="Неактивная ферма", access_token="tok-inactive")
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    assert resolve_seller_access("tok-inactive", session) is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `uv run pytest tests/test_seller_access.py -v`
Expected: FAIL — `TypeError: resolve_seller_access() takes 1 positional argument but 2 were given` (текущая сигнатура — `(access_token, *, tokens_json=None)`).

- [ ] **Step 3: Переписать `seller_access.py`**

Заменить всё содержимое `app/publication/seller_access.py`:

```python
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.platform.seller_gateway import SellerGateway


@dataclass(frozen=True)
class SellerAccess:
    seller_id: int
    published_by: int
    name: str


def resolve_seller_access(access_token: str, session: Session) -> SellerAccess | None:
    """Резолвит access_token продавца в (seller_id, published_by) через
    SellerGateway (Anti-Corruption Layer к таблице Seller) — единственный
    источник этой связки на стороне API: клиент не передаёт seller_id/
    published_by напрямую (иначе любой мог опубликовать каталог от чужого
    имени). access_token хранится в Seller.access_token, выдаётся через
    POST /api/v1/seller/activate — не в .env/SELLER_ACCESS_TOKENS, см.
    docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md."""
    row = SellerGateway(session).find_by_access_token(access_token)
    if row is None:
        return None
    return SellerAccess(seller_id=row.seller_id, published_by=row.user_id, name=row.name)
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/test_seller_access.py -v`
Expected: PASS (все 3).

- [ ] **Step 5: Commit**

```bash
git add app/publication/seller_access.py tests/test_seller_access.py
git commit -m "GreenMarket: resolve_seller_access() — переезд с SELLER_ACCESS_TOKENS на БД"
```

---

### Task 5: Подключить сессию к резолверу + убрать `SELLER_ACCESS_TOKENS`

**Files:**
- Modify: `app/api/v1/publications.py:33-36`
- Modify: `app/api/v1/photos.py:28-29`
- Modify: `app/core/config.py:14`

- [ ] **Step 1: `publications.py` — резолвер получает `session`**

Заменить:

```python
def get_seller_access_resolver():
    """Переопределяется в тестах фейковым резолвером токенов —
    см. `backend/tests/test_publications_api.py::override_seller_access`."""
    return resolve_seller_access
```

на:

```python
def get_seller_access_resolver(session: Session = Depends(get_session)):
    """Переопределяется в тестах фейковым резолвером токенов —
    см. `backend/tests/test_publications_api.py::override_seller_access`.
    По умолчанию — резолвер, привязанный к session текущего запроса
    (access_token резолвится через БД, см. seller_access.py)."""
    return lambda access_token: resolve_seller_access(access_token, session)
```

(`Depends`, `Session`, `get_session` уже импортированы в этом файле — новых импортов не требуется.)

- [ ] **Step 2: `photos.py` — тот же резолвер получает `session`**

Заменить:

```python
def get_seller_access_resolver():
    return resolve_seller_access
```

на:

```python
def get_seller_access_resolver(session: Session = Depends(get_session)):
    return lambda access_token: resolve_seller_access(access_token, session)
```

(`Depends`, `Session`, `get_session` уже импортированы в этом файле.)

- [ ] **Step 3: `config.py` — убрать настройку**

Удалить строку:

```python
    seller_access_tokens: str = "{}"
```

из `app/core/config.py` (класс `Settings`).

- [ ] **Step 4: Полный прогон всего backend-набора**

Run: `uv run pytest -v`
Expected: все тесты проходят (существующие `test_publications_api.py`/`test_seller_api.py`/`test_photos_api.py` переопределяют `get_seller_access_resolver` целиком через `app.dependency_overrides` — сигнатура с `Depends` внутри не используется, когда зависимость подменена, так что регрессий быть не должно).

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/publications.py app/api/v1/photos.py app/core/config.py
git commit -m "GreenMarket: get_seller_access_resolver — резолвинг через БД, SELLER_ACCESS_TOKENS удалён"
```

---

### Task 6: Endpoint `POST /api/v1/seller/activate`

**Files:**
- Modify: `app/api/v1/seller_schemas.py`
- Modify: `app/api/v1/seller.py`
- Test: Create `tests/test_seller_activation_api.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_seller_activation_api.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app
from app.publication.seller_activation import issue_activation_code


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def test_activate_returns_access_token_for_valid_code(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец для API-активации")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)

    response = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-api-1"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert len(response.json()["access_token"]) > 20


def test_activate_rejects_unknown_code(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.post(
        "/api/v1/seller/activate", json={"activation_code": "not-a-real-code", "spreadsheet_id": "sheet-x"}
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_CODE"


def test_activate_rejects_reused_code(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец для повторного кода")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)
    first = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-first"})
    assert first.status_code == 200

    second = client.post("/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-second"})

    app.dependency_overrides.clear()
    assert second.status_code == 400


def test_activated_token_resolves_via_seller_catalog_endpoint(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец сквозной проверки")
    code = issue_activation_code(seller_id, session=committing_session)
    override_session(committing_session)
    client = TestClient(app)

    activate_response = client.post(
        "/api/v1/seller/activate", json={"activation_code": code, "spreadsheet_id": "sheet-e2e"}
    )
    token = activate_response.json()["access_token"]

    status_response = client.get("/api/v1/seller/catalog", params={"access_token": token})

    app.dependency_overrides.clear()
    assert status_response.status_code == 200
    assert status_response.json()["seller_id"] == seller_id
```

Обратите внимание: последний тест **не** переопределяет `get_seller_access_resolver` — он проверяет реальный путь `activate → resolve_seller_access` целиком через БД, без фейкового резолвера.

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `uv run pytest tests/test_seller_activation_api.py -v`
Expected: FAIL — `404 Not Found` (`POST /api/v1/seller/activate` ещё не существует).

- [ ] **Step 3: Добавить схемы в `seller_schemas.py`**

Добавить в конец `app/api/v1/seller_schemas.py`:

```python
class SellerActivationRequest(BaseModel):
    activation_code: str
    spreadsheet_id: str


class SellerActivationResponse(BaseModel):
    access_token: str
```

- [ ] **Step 4: Добавить endpoint в `seller.py`**

Изменить импорт схем:

```python
from app.api.v1.seller_schemas import SellerActivationRequest, SellerActivationResponse, SellerStatusResponse
```

Добавить импорт функции активации:

```python
from app.publication.seller_activation import activate_seller
```

Добавить endpoint (после `get_seller_catalog`):

```python
@router.post("/activate", response_model=SellerActivationResponse)
def activate(
    request: SellerActivationRequest,
    session: Session = Depends(get_session),
) -> SellerActivationResponse | JSONResponse:
    access_token = activate_seller(request.activation_code, spreadsheet_id=request.spreadsheet_id, session=session)
    if access_token is None:
        return error_response(400, "INVALID_ACTIVATION_CODE", "Код активации недействителен.")

    session.commit()
    return SellerActivationResponse(access_token=access_token)
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `uv run pytest tests/test_seller_activation_api.py -v`
Expected: PASS (все 4).

- [ ] **Step 6: Полный прогон всего backend-набора**

Run: `uv run pytest -v`
Expected: все тесты проходят.

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/seller_schemas.py app/api/v1/seller.py tests/test_seller_activation_api.py
git commit -m "GreenMarket: POST /api/v1/seller/activate — обмен activation_code на access_token"
```

---

### Task 7: CLI-скрипт для выдачи кода (admin-only)

**Files:**
- Create: `scripts/issue_activation_code.py`

- [ ] **Step 1: Написать скрипт**

Создать `backend/scripts/issue_activation_code.py`:

```python
"""Admin CLI: выдать/перевыпустить activation_code для существующего продавца.

Использование (из backend/):
    uv run python scripts/issue_activation_code.py <seller_id>

Печатает код в stdout — админ передаёт его продавцу вручную (WhatsApp/
телефон, оба поля обязательны в Seller_Profile.md). См.
docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md.
"""

import argparse
import sys

from app.infrastructure.database import SessionLocal
from app.publication.seller_activation import issue_activation_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Выдать activation_code продавцу")
    parser.add_argument("seller_id", type=int)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        code = issue_activation_code(args.seller_id, session=session)
        if code is None:
            print(f"Seller {args.seller_id} не найден", file=sys.stderr)
            raise SystemExit(1)
        session.commit()
    finally:
        session.close()

    print(f"activation_code: {code}")


if __name__ == "__main__":
    main()
```

Логика (`issue_activation_code()`) уже покрыта тестами в Task 3 — этот файл тонкий CLI-обвязчик, отдельный тест не пишем (YAGNI, аналогично тому, как фронтенды в проекте проверяются вручную, а не автотестами, см. `backend/README.md`).

- [ ] **Step 2: Ручная проверка на локальной БД**

Создать тестового продавца (если нет ни одного под рукой):

Run: `mysql -u root -p greenmarket -e "INSERT INTO users (name) VALUES ('Тестовый продавец для CLI'); INSERT INTO Seller (user_id) VALUES (LAST_INSERT_ID());"`

Run: `uv run python scripts/issue_activation_code.py <id только что созданного Seller>`
Expected: строка вида `activation_code: a1b2c3d4` в stdout, без ошибок.

Run: `mysql -u root -p greenmarket -e "SELECT activation_code, activation_code_expires_at FROM Seller ORDER BY id DESC LIMIT 1;"`
Expected: код совпадает с напечатанным, `activation_code_expires_at` — примерно через 7 дней от текущего момента.

- [ ] **Step 3: Commit**

```bash
git add scripts/issue_activation_code.py
git commit -m "GreenMarket: scripts/issue_activation_code.py — admin CLI выдачи кода активации"
```

---

### Task 8: Документация — `REST_API.md`

**Files:**
- Modify: `docs/04-services/REST_API.md`

- [ ] **Step 1: Убрать упоминания `SELLER_ACCESS_TOKENS` из Publication API**

Заменить (раздел Publication API, `POST /api/v1/publications`):

```
Сервер резолвит `access_token` в `seller_id`/`published_by` (`SELLER_ACCESS_TOKENS`) — клиент их не передаёт напрямую
```

на:

```
Сервер резолвит `access_token` в `seller_id`/`published_by` (таблица `Seller`, см. Seller API — `POST /activate`) — клиент их не передаёт напрямую
```

- [ ] **Step 2: Убрать упоминание `SELLER_ACCESS_TOKENS` из описания `POST /api/v1/photos`**

Заменить:

```
Сервер резолвит `access_token` в `seller_id` (тот же `SELLER_ACCESS_TOKENS`, что и остальной Publication API)
```

на:

```
Сервер резолвит `access_token` в `seller_id` (та же таблица `Seller`, что и остальной Publication/Seller API)
```

- [ ] **Step 3: Добавить `POST /api/v1/seller/activate` в раздел Seller API**

Заменить заголовок раздела и первую строку:

```
## Seller API

Используется Seller Cabinet.
```

на:

```
## Seller API

Используется Seller Cabinet (и Apps Script карточки товара — обмен `activation_code` на `access_token`, см. `apps_script/product_card/`).

- `POST /api/v1/seller/activate` — первичная привязка персональной копии Google Sheets к продавцу. Тело `{"activation_code": str, "spreadsheet_id": str}`. Ответ — `{"access_token": str}`, который клиент сохраняет и в дальнейшем передаёт как обычный `access_token` во все остальные Seller/Publication-эндпоинты. Код активации одноразовый, с TTL (7 дней), выдаётся администратором вне API (`scripts/issue_activation_code.py`) — самостоятельной регистрации нет, `Seller.user_id` обязан ссылаться на уже существующего пользователя платформы (см. `Seller_Profile.md`, `003_create_seller.sql`).
```

(Остальные строки раздела Seller API — `GET /catalog`, `/catalog/template`, `/catalog/errors` — не трогаем.)

- [ ] **Step 4: Commit**

```bash
git add docs/04-services/REST_API.md
git commit -m "GreenMarket: документация — POST /api/v1/seller/activate, убраны упоминания SELLER_ACCESS_TOKENS"
```

---

### Task 9: Apps Script — обмен кода активации вместо ручного ввода токена

**Files:**
- Modify: `apps_script/product_card/Code.gs`

Нет автоматизированной тестовой инфраструктуры для Apps Script (проектная практика — фронтенды проверяются вручную в браузере, см. `backend/README.md`). Все шаги ниже — код + ручная проверка.

- [ ] **Step 1: Добавить константу URL личного кабинета**

В начало файла, после `var API_BASE_URL = ...`:

```javascript
var SELLER_CABINET_URL = 'https://CHANGE_ME.example.com/seller/'; // TODO: заменить на реальный адрес Seller Cabinet перед деплоем
```

- [ ] **Step 2: Добавить пункт меню «Личный кабинет»**

Заменить:

```javascript
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addToUi();
}
```

на:

```javascript
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addItem('Личный кабинет', 'openSellerCabinet')
    .addToUi();
}
```

- [ ] **Step 3: Переписать `getOrPromptAccessToken()` на обмен activation_code**

Заменить:

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
```

на:

```javascript
function getOrPromptAccessToken() {
  var props = PropertiesService.getDocumentProperties();
  var token = props.getProperty(ACCESS_TOKEN_PROPERTY);
  if (token) return token;

  var ui = SpreadsheetApp.getUi();
  var result = ui.prompt(
    'Активация доступа',
    'Введите код активации, полученный от администратора GreenMarket:',
    ui.ButtonSet.OK_CANCEL
  );
  if (result.getSelectedButton() !== ui.Button.OK) return null;

  var activationCode = result.getResponseText().trim();
  if (!activationCode) return null;

  token = activateAccess_(activationCode);
  if (!token) {
    ui.alert('Код активации недействителен, просрочен или уже использован. Обратитесь к администратору за новым кодом.');
    return null;
  }

  props.setProperty(ACCESS_TOKEN_PROPERTY, token);
  return token;
}

function activateAccess_(activationCode) {
  var response = UrlFetchApp.fetch(API_BASE_URL + '/seller/activate', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      activation_code: activationCode,
      spreadsheet_id: SpreadsheetApp.getActiveSpreadsheet().getId(),
    }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) return null;
  return JSON.parse(response.getContentText()).access_token;
}
```

- [ ] **Step 4: Добавить `openSellerCabinet()`**

Добавить в конец файла:

```javascript
function openSellerCabinet() {
  var token = getOrPromptAccessToken();
  if (!token) return;

  var url = SELLER_CABINET_URL + '?token=' + encodeURIComponent(token);
  var html = HtmlService
    .createHtmlOutput('<a href="' + url + '" target="_blank">Открыть личный кабинет</a>')
    .setWidth(320)
    .setHeight(80);
  SpreadsheetApp.getUi().showModalDialog(html, 'Личный кабинет');
}
```

- [ ] **Step 5: Задеплоить на тестовую копию и проверить вручную**

Задеплоить обновлённый `Code.gs` (`clasp push` или вставка в редактор Apps Script) на копию рабочей книги, у которой в `PropertiesService` ещё нет `GREENMARKET_ACCESS_TOKEN` (свежая копия — Document Properties не копируются между оригиналом и копией, см. design doc).

Получить реальный `activation_code` для тестового продавца:
Run (из `backend/`): `uv run python scripts/issue_activation_code.py <seller_id тестового продавца>`

В тестовой копии таблицы:
1. Выбрать «GreenMarket → Личный кабинет» (или «Добавить товар» — любое действие, идущее через `getOrPromptAccessToken()`).
2. Ввести полученный код в диалоге «Активация доступа».
3. Ожидаемо: диалог закрывается без ошибки, повторный вызов «Личный кабинет» сразу открывает диалог со ссылкой (без повторного запроса кода).
4. Кликнуть по ссылке «Открыть личный кабинет» — должен открыться Seller Cabinet с реальными данными этого продавца (не «Нет доступа»).
5. Повторно ввести **тот же** код на другой свежей копии (или после ручного `PropertiesService.getDocumentProperties().deleteAllProperties()` через редактор скрипта) — ожидаемо: alert «Код активации недействителен...».

- [ ] **Step 6: Commit**

```bash
git add apps_script/product_card/Code.gs
git commit -m "GreenMarket: Apps Script — обмен activation_code на access_token вместо ручного ввода токена"
```

---

## Итоговая проверка

- [ ] Run: `uv run pytest` (из `backend/`) — весь backend-набор зелёный.
- [ ] Ручная проверка: сквозной сценарий Task 9 Step 5 пройден на реальной тестовой копии Google Sheets.
- [ ] На сервере (`104.171.133.95`) после деплоя: перенести существующие демо-токены из `SELLER_ACCESS_TOKENS` (`.env`) в БД вручную (`UPDATE Seller SET access_token = '<старый токен>' WHERE id = <seller_id>` для каждого demo-продавца, чтобы уже выданные ссылки не сломались), затем убрать `SELLER_ACCESS_TOKENS` из `.env` — вне охвата автотестов, ручная миграция данных перед выкладкой.

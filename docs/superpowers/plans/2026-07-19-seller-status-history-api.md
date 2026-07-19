# Seller Status + Publication History API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the two missing `Seller API` endpoints (`GET /api/v1/seller/catalog`, `GET /api/v1/publications`) and wire them into Экраны 1 («Главная») и 5 («История публикаций») of Seller Cabinet, so all 4 reachable screens (Главная / История / Публикация / Ошибки) work against real data.

**Architecture:** Follows the exact layered pattern already established by Catalog API/Publication API — `APIRouter` → `Repository`/`Gateway` → ORM/raw-SQL, `access_token` resolved via the existing `resolve_seller_access`. One additive migration (`CatalogPublication` gains `created_count`/`updated_count`/`deactivated_count` — currently only live in the transient `PublicationResult`, never persisted, which is why history can't show them today). Frontend stays a router-less `useState` shell, consistent with Buyer Web/Seller Cabinet's existing minimalism — no new dependencies.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend, `uv`), React/TypeScript/Vite (seller-cabinet), MySQL 8.

**Spec:** [`docs/superpowers/specs/2026-07-19-seller-status-history-api-design.md`](../specs/2026-07-19-seller-status-history-api-design.md)

---

### Task 1: Migration 009 — persist publication counts

**Files:**
- Create: `database/migrations/009_alter_catalog_publications_add_counts.sql`
- Modify: `backend/app/infrastructure/models.py` (`CatalogPublication` class)
- Modify: `docs/03-database/Database_Migrations.md`

- [ ] **Step 1: Write the migration file**

```sql
-- Migration : 009_alter_catalog_publications_add_counts.sql
-- Purpose   : created_count/updated_count/deactivated_count существовали только в
--             одноразовом PublicationResult (backend/app/publication/publication_result.py)
--             и никогда не сохранялись — без них Экран 5 Seller Cabinet
--             (docs/05-ui/Seller_MVP.md) не может показать историю публикаций.
-- DBMS      : MySQL Community Server 8.0.16+

ALTER TABLE CatalogPublication
    ADD COLUMN created_count     INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Создано SellerProduct при этой публикации',
    ADD COLUMN updated_count     INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Обновлено SellerProduct при этой публикации',
    ADD COLUMN deactivated_count INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Деактивировано SellerProduct при этой публикации';
```

- [ ] **Step 2: Apply it to your local dev DB**

Same DB you already use for `uv run pytest` (per `backend/README.md` — Docker MySQL, adjust host/port/user/password to your own `backend/.env`):

```bash
mysql -h127.0.0.1 -P3307 -uroot -p<пароль> greenmarket < database/migrations/009_alter_catalog_publications_add_counts.sql
```

Verify: `mysql ... -e "DESCRIBE CatalogPublication;" greenmarket` should list the 3 new columns.

- [ ] **Step 3: Add the 3 columns to the ORM model**

In `backend/app/infrastructure/models.py`, find the `CatalogPublication` class (currently ends after `published_by`) and add:

```python
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    deactivated_count: Mapped[int] = mapped_column(Integer, default=0)
```

(right after the existing `published_by: Mapped[int] = mapped_column(Integer)` line, before the class ends)

- [ ] **Step 4: Update `Database_Migrations.md`**

In the `## Порядок применения` code block, change:

```text
001 → 002 → 003 → 004 → 005 → 006 → 007 → 008
```
to:
```text
001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009
```

In the `## Состав миграций Stage 1` table, add a row after the `008` row:

```markdown
| `009_alter_catalog_publications_add_counts.sql` | расширение таблицы `CatalogPublication` полями `created_count`, `updated_count`, `deactivated_count` |
```

- [ ] **Step 5: Commit**

```bash
git add database/migrations/009_alter_catalog_publications_add_counts.sql backend/app/infrastructure/models.py docs/03-database/Database_Migrations.md
git commit -m "Миграция 009: CatalogPublication — created/updated/deactivated_count"
```

---

### Task 2: `CatalogPublicationRepository` — persist and list counts

**Files:**
- Modify: `backend/app/infrastructure/repositories/catalog_publication_repository.py`
- Test: `backend/tests/test_catalog_publication_repository.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_catalog_publication_repository.py`:

```python
def test_create_persists_counts(session):
    seller_id, user_id = insert_seller_and_user(session, name="Продавец со счётчиками")
    repository = CatalogPublicationRepository(session)

    publication = repository.create(
        seller_id=seller_id, version=1, publication_key="key-counts", catalog_hash="hash-counts",
        published_by=user_id, created_count=2, updated_count=1, deactivated_count=3,
    )

    assert publication.created_count == 2
    assert publication.updated_count == 1
    assert publication.deactivated_count == 3


def test_create_defaults_counts_to_zero_when_not_given(session):
    seller_id, user_id = insert_seller_and_user(session, name="Продавец без счётчиков")
    repository = CatalogPublicationRepository(session)

    publication = repository.create(
        seller_id=seller_id, version=1, publication_key="key-default", catalog_hash="hash-default", published_by=user_id
    )

    assert publication.created_count == 0
    assert publication.updated_count == 0
    assert publication.deactivated_count == 0


def test_list_by_seller_orders_newest_version_first(session):
    seller_id, user_id = insert_seller_and_user(session, name="Продавец с историей")
    repository = CatalogPublicationRepository(session)
    repository.create(seller_id=seller_id, version=1, publication_key="key-hist-1", catalog_hash="hash-hist-1", published_by=user_id, created_count=1)
    repository.create(seller_id=seller_id, version=2, publication_key="key-hist-2", catalog_hash="hash-hist-2", published_by=user_id, updated_count=1)

    result = repository.list_by_seller(seller_id)

    assert [p.version for p in result] == [2, 1]


def test_list_by_seller_returns_empty_list_for_seller_never_published(session):
    seller_id, _ = insert_seller_and_user(session, name="Продавец без истории")
    assert CatalogPublicationRepository(session).list_by_seller(seller_id) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_catalog_publication_repository.py -v`
Expected: FAIL — `create()` doesn't accept `created_count`/`updated_count`/`deactivated_count` (`TypeError: unexpected keyword argument`), and `list_by_seller` doesn't exist (`AttributeError`).

- [ ] **Step 3: Implement**

In `backend/app/infrastructure/repositories/catalog_publication_repository.py`, replace `create()`:

```python
    def create(
        self,
        *,
        seller_id: int,
        version: int,
        publication_key: str,
        catalog_hash: str,
        published_by: int,
        created_count: int = 0,
        updated_count: int = 0,
        deactivated_count: int = 0,
    ) -> CatalogPublication:
        publication = CatalogPublication(
            seller_id=seller_id,
            version=version,
            publication_key=publication_key,
            catalog_hash=catalog_hash,
            published_at=datetime.now(timezone.utc),
            published_by=published_by,
            created_count=created_count,
            updated_count=updated_count,
            deactivated_count=deactivated_count,
        )
        self.session.add(publication)
        self.session.flush()
        return publication
```

And add a new method (after `exists_with_key`, before `create`):

```python
    def list_by_seller(self, seller_id: int) -> list[CatalogPublication]:
        return (
            self.session.query(CatalogPublication)
            .filter(CatalogPublication.seller_id == seller_id)
            .order_by(CatalogPublication.version.desc())
            .all()
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_catalog_publication_repository.py -v`
Expected: PASS (all tests in the file, including the 4 new ones and the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/repositories/catalog_publication_repository.py backend/tests/test_catalog_publication_repository.py
git commit -m "CatalogPublicationRepository: сохранять счётчики публикации + list_by_seller"
```

---

### Task 3: `PublicationService` — pass counts through to the repository

**Files:**
- Modify: `backend/app/publication/publication_service.py:68-74`
- Test: `backend/tests/test_publication_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_publication_service.py`:

```python
def test_publish_persists_counts_on_the_publication_record(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма счётчики в истории")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    model = make_model(
        seller_id,
        [make_product(seller_name="Ферма А", price=50), make_product(seller_name="Ферма Б", price=80)],
    )
    result = service.publish(model, published_by=user_id, publication_key="counts-key-1", catalog_hash="counts-hash-1")

    publication = CatalogPublicationRepository(committing_session).list_by_seller(seller_id)[0]
    assert publication.created_count == result.created_count == 2
    assert publication.updated_count == result.updated_count == 0
    assert publication.deactivated_count == result.deactivated_count == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_publication_service.py::test_publish_persists_counts_on_the_publication_record -v`
Expected: FAIL — `publication.created_count` is `0` (default), not `2`, because `PublicationService.publish()` never passes the counts through.

- [ ] **Step 3: Implement**

In `backend/app/publication/publication_service.py`, replace the `catalog_publication_repository.create(...)` call (currently lines 68-74):

```python
            publication = self.catalog_publication_repository.create(
                seller_id=seller_id,
                version=new_version,
                publication_key=publication_key,
                catalog_hash=catalog_hash,
                published_by=published_by,
                created_count=created,
                updated_count=updated,
                deactivated_count=deactivated,
            )
```

- [ ] **Step 4: Run the full publication service test file to verify no regression**

Run: `cd backend && uv run pytest tests/test_publication_service.py -v`
Expected: PASS — all tests, including the new one.

- [ ] **Step 5: Commit**

```bash
git add backend/app/publication/publication_service.py backend/tests/test_publication_service.py
git commit -m "PublicationService: передавать created/updated/deactivated в журнал публикаций"
```

---

### Task 4: `SellerProductRepository.count_published`

**Files:**
- Modify: `backend/app/infrastructure/repositories/seller_product_repository.py`
- Test: `backend/tests/test_seller_product_repository.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_seller_product_repository.py`:

```python
def test_count_published_counts_only_published(session):
    seller_id = insert_seller(session, name="Продавец для count_published")
    repository = SellerProductRepository(session)
    repository.create(seller_id=seller_id, product_id=None, seller_name="Опубликован для count", price=1, stock=1, unit="шт", description=None)
    unpublished = repository.create(seller_id=seller_id, product_id=None, seller_name="Не опубликован для count", price=1, stock=1, unit="шт", description=None)
    session.execute(text("UPDATE SellerProduct SET is_published = FALSE WHERE id = :id"), {"id": unpublished.id})

    assert repository.count_published(seller_id) == 1


def test_count_published_returns_zero_for_seller_without_products(session):
    seller_id = insert_seller(session, name="Продавец без товаров для count_published")
    assert SellerProductRepository(session).count_published(seller_id) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_seller_product_repository.py -v`
Expected: FAIL — `AttributeError: 'SellerProductRepository' object has no attribute 'count_published'`.

- [ ] **Step 3: Implement**

In `backend/app/infrastructure/repositories/seller_product_repository.py`, add (after `list_by_seller`, before `list_published_for_products`):

```python
    def count_published(self, seller_id: int) -> int:
        return (
            self.session.query(SellerProduct)
            .filter(SellerProduct.seller_id == seller_id, SellerProduct.is_published.is_(True))
            .count()
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_seller_product_repository.py -v`
Expected: PASS — all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/repositories/seller_product_repository.py backend/tests/test_seller_product_repository.py
git commit -m "SellerProductRepository: count_published"
```

---

### Task 5: `SellerGateway.get_status`

**Files:**
- Modify: `backend/app/platform/seller_gateway.py`
- Test: `backend/tests/test_seller_gateway.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_seller_gateway.py`:

```python
def test_get_status_returns_active_flag_and_version(session):
    seller_id = insert_seller(session, name="Продавец статус", publication_key="key", catalog_hash="hash")
    session.execute(
        text("UPDATE Seller SET is_active = TRUE, current_catalog_version = 3 WHERE id = :id"), {"id": seller_id}
    )

    status = SellerGateway(session).get_status(seller_id)

    assert status.is_active is True
    assert status.current_catalog_version == 3


def test_get_status_defaults_version_to_zero_when_never_published(session):
    seller_id = insert_seller(session, name="Продавец без публикаций для статуса", publication_key=None, catalog_hash=None)

    status = SellerGateway(session).get_status(seller_id)

    assert status.current_catalog_version == 0


def test_get_status_returns_none_for_missing_seller(session):
    assert SellerGateway(session).get_status(999_999) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_seller_gateway.py -v`
Expected: FAIL — `AttributeError: 'SellerGateway' object has no attribute 'get_status'`.

- [ ] **Step 3: Implement**

In `backend/app/platform/seller_gateway.py`, add the import and dataclass at the top, and the method on the class:

```python
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SellerStatus:
    is_active: bool
    current_catalog_version: int


class SellerGateway:
```

(keep the existing docstring and `__init__`, then add this method, e.g. right after `__init__`):

```python
    def get_status(self, seller_id: int) -> SellerStatus | None:
        row = self.session.execute(
            text("SELECT is_active, current_catalog_version FROM Seller WHERE id = :seller_id"),
            {"seller_id": seller_id},
        ).first()
        if row is None:
            return None
        return SellerStatus(is_active=bool(row[0]), current_catalog_version=row[1] or 0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_seller_gateway.py -v`
Expected: PASS — all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/platform/seller_gateway.py backend/tests/test_seller_gateway.py
git commit -m "SellerGateway: get_status (is_active + current_catalog_version)"
```

---

### Task 6: `GET /api/v1/seller/catalog` — seller status endpoint

**Files:**
- Create: `backend/app/api/v1/seller_schemas.py`
- Create: `backend/app/api/v1/seller.py`
- Test: Create `backend/tests/test_seller_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_seller_api.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.publications import get_seller_access_resolver
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.main import app
from app.publication.seller_access import SellerAccess

VALID_TOKEN = "seller-api-test-token"


def override_seller_access(seller_id: int, published_by: int) -> None:
    access = SellerAccess(seller_id=seller_id, published_by=published_by, name="Тестовый продавец")
    app.dependency_overrides[get_seller_access_resolver] = lambda: (lambda token: access if token == VALID_TOKEN else None)


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def insert_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def test_get_seller_catalog_returns_status_for_never_published_seller(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец без публикаций API")
    override_session(committing_session)
    override_seller_access(seller_id, seller_id)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["seller_id"] == seller_id
    assert body["current_catalog_version"] == 0
    assert body["published_product_count"] == 0
    assert body["last_published_at"] is None


def test_get_seller_catalog_reflects_real_publication(committing_session):
    seller_id = insert_seller(committing_session, name="Продавец с публикацией API")
    user_id = insert_user(committing_session, name="Admin API")
    CatalogPublicationRepository(committing_session).create(
        seller_id=seller_id, version=1, publication_key="seller-api-key", catalog_hash="seller-api-hash",
        published_by=user_id, created_count=2,
    )
    committing_session.execute(text("UPDATE Seller SET current_catalog_version = 1 WHERE id = :id"), {"id": seller_id})
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["current_catalog_version"] == 1
    assert body["last_published_at"] is not None


def test_get_seller_catalog_rejects_invalid_token(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": "not-a-real-token"})

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"


def test_get_seller_catalog_returns_404_for_token_with_no_seller_row(committing_session):
    # Токен резолвится (не 403), но указывает на несуществующий seller_id —
    # ошибка конфигурации SELLER_ACCESS_TOKENS, а не проблема доступа.
    override_session(committing_session)
    override_seller_access(999_999, 1)
    client = TestClient(app)

    response = client.get("/api/v1/seller/catalog", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SELLER_NOT_FOUND"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_seller_api.py -v`
Expected: FAIL to collect — `app.api.v1.seller_schemas`/`app.api.v1.seller` don't exist yet, and `/api/v1/seller/catalog` isn't a registered route (404 on all requests once the import error is fixed with a dummy module, so treat any pre-implementation failure as expected RED).

- [ ] **Step 3: Implement the schema**

Create `backend/app/api/v1/seller_schemas.py`:

```python
from datetime import datetime

from pydantic import BaseModel


class SellerStatusResponse(BaseModel):
    seller_id: int
    is_active: bool
    current_catalog_version: int
    published_product_count: int
    last_published_at: datetime | None
```

- [ ] **Step 4: Implement the router**

Create `backend/app/api/v1/seller.py`:

```python
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.publications import get_seller_access_resolver
from app.api.v1.schemas import error_response
from app.api.v1.seller_schemas import SellerStatusResponse
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.seller_gateway import SellerGateway

router = APIRouter(prefix="/api/v1/seller", tags=["seller"])


@router.get("/catalog", response_model=SellerStatusResponse)
def get_seller_catalog(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerStatusResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    status = SellerGateway(session).get_status(access.seller_id)
    if status is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {access.seller_id} не найден")

    publications = CatalogPublicationRepository(session).list_by_seller(access.seller_id)
    last_published_at = publications[0].published_at if publications else None

    return SellerStatusResponse(
        seller_id=access.seller_id,
        is_active=status.is_active,
        current_catalog_version=status.current_catalog_version,
        published_product_count=SellerProductRepository(session).count_published(access.seller_id),
        last_published_at=last_published_at,
    )
```

Note: this reuses `get_seller_access_resolver` from `app/api/v1/publications.py` (same dependency-override key `POST /publications`'s tests already use) rather than defining a second one — one override point for both routers.

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add the import and registration so `TestClient(app)` actually sees the new route:

```python
from app.api.v1.seller import router as seller_router
```
(alongside the existing `catalog_router`/`publications_router` imports)

```python
app.include_router(seller_router)
```
(alongside the existing two `app.include_router(...)` calls)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_seller_api.py -v`
Expected: PASS — all 4 tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/seller_schemas.py backend/app/api/v1/seller.py backend/app/main.py backend/tests/test_seller_api.py
git commit -m "Seller API: GET /api/v1/seller/catalog (статус продавца)"
```

---

### Task 7: `GET /api/v1/publications` — publication history endpoint

**Files:**
- Modify: `backend/app/api/v1/schemas.py`
- Modify: `backend/app/api/v1/publications.py`
- Test: `backend/tests/test_publications_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_publications_api.py`:

```python
def test_get_publications_returns_empty_history_for_new_seller(committing_session):
    from fastapi.testclient import TestClient

    seller_id = insert_seller(committing_session, name="Продавец без истории API")
    override_session(committing_session)
    override_seller_access(seller_id, seller_id)
    client = TestClient(app)

    response = client.get("/api/v1/publications", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"publications": []}


def test_get_publications_returns_history_newest_first(committing_session):
    from fastapi.testclient import TestClient
    from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository

    seller_id = insert_seller(committing_session, name="Продавец с историей API")
    user_id = insert_user(committing_session, name="Admin история")
    repo = CatalogPublicationRepository(committing_session)
    repo.create(seller_id=seller_id, version=1, publication_key="hist-key-1", catalog_hash="hist-hash-1", published_by=user_id, created_count=2)
    repo.create(seller_id=seller_id, version=2, publication_key="hist-key-2", catalog_hash="hist-hash-2", published_by=user_id, updated_count=1)
    override_session(committing_session)
    override_seller_access(seller_id, user_id)
    client = TestClient(app)

    response = client.get("/api/v1/publications", params={"access_token": VALID_TOKEN})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert [p["version"] for p in body["publications"]] == [2, 1]
    assert body["publications"][1]["created"] == 2


def test_get_publications_rejects_invalid_token(committing_session):
    from fastapi.testclient import TestClient

    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/publications", params={"access_token": "not-a-real-token"})

    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELLER_ACCESS_DENIED"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_publications_api.py -v -k get_publications`
Expected: FAIL — `405 Method Not Allowed` (no `GET` handler registered on `/api/v1/publications` yet).

- [ ] **Step 3: Implement the schema**

In `backend/app/api/v1/schemas.py`, add `datetime` to the imports and append at the end of the file:

```python
from datetime import datetime
```
(add to the existing `import re` line block at the top)

```python
class PublicationHistoryItem(BaseModel):
    version: int
    published_at: datetime
    created: int
    updated: int
    deactivated: int


class PublicationHistoryResponse(BaseModel):
    publications: list[PublicationHistoryItem]
```

- [ ] **Step 4: Implement the endpoint**

In `backend/app/api/v1/publications.py`, add to the imports:

```python
from app.api.v1.schemas import (
    PublicationHistoryItem,
    PublicationHistoryResponse,
    PublicationRequest,
    PublicationResponse,
    ValidationErrorDetail,
    error_response,
)
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
```

(replacing the existing single-line `from app.api.v1.schemas import ...` import)

Then add the new route (after the existing `@router.post("", ...)` handler, at the end of the file):

```python
@router.get("", response_model=PublicationHistoryResponse)
def list_publications(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> PublicationHistoryResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    publications = CatalogPublicationRepository(session).list_by_seller(access.seller_id)
    return PublicationHistoryResponse(
        publications=[
            PublicationHistoryItem(
                version=p.version,
                published_at=p.published_at,
                created=p.created_count,
                updated=p.updated_count,
                deactivated=p.deactivated_count,
            )
            for p in publications
        ]
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_publications_api.py -v`
Expected: PASS — the full file, including the 3 new tests and all pre-existing ones (no regression on `POST`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/schemas.py backend/app/api/v1/publications.py backend/tests/test_publications_api.py
git commit -m "Publication API: GET /api/v1/publications (история публикаций продавца)"
```

---

### Task 8: Full backend regression check

**Files:** none (verification checkpoint before moving to docs/frontend)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS — every test in the suite (pre-existing tests plus all of Tasks 2-7's new tests), no regressions from the migration, repository changes, or the two new routes.

If anything fails, fix it in the task that introduced the regression and re-run — do not proceed to Task 9 with a red suite.

---

### Task 9: Sync `REST_API.md` with real behavior

**Files:**
- Modify: `docs/04-services/REST_API.md`

- [ ] **Step 1: Fix the Publication API section**

Replace:

```markdown
- `POST /api/v1/publications` — создание публикации. `Content-Type: application/json`, тело `{"seller_id": int, "published_by": int, "sheet_url": str}` (либо `spreadsheet_id` вместо `sheet_url`, если клиент уже разобрал ссылку). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации (`publication_id`, `created`, `updated`, `deactivated`), либо список ошибок валидации (`422`).
- `GET /api/v1/publications` — история публикаций продавца.
```

with:

```markdown
- `POST /api/v1/publications` — создание публикации. `Content-Type: application/json`, тело `{"access_token": str, "sheet_url": str}` (либо `spreadsheet_id` вместо `sheet_url`). Сервер резолвит `access_token` в `seller_id`/`published_by` (`SELLER_ACCESS_TOKENS`) — клиент их не передаёт напрямую (закрыто 19.07 — была дыра безопасности, открытый `seller_id` позволял публиковать от чужого имени). Публикация выполняется синхронно в рамках одного HTTP-запроса. Ответ возвращается только после завершения всей операции и содержит либо успешный результат публикации (`publication_id`, `created`, `updated`, `deactivated`, `mode`), либо список ошибок валидации (`422`).
- `GET /api/v1/publications?access_token=...` — история публикаций продавца, версии по убыванию (`version`, `published_at`, `created`, `updated`, `deactivated`).
```

- [ ] **Step 2: Fix the Seller API section**

Replace:

```markdown
## Seller API

Используется Seller Cabinet.

- `GET /api/v1/seller/catalog` — текущий каталог.
- `GET /api/v1/seller/catalog/template` — шаблон Excel.
- `GET /api/v1/seller/catalog/errors` — ошибки последней публикации.
```

with:

```markdown
## Seller API

Используется Seller Cabinet.

- `GET /api/v1/seller/catalog?access_token=...` — статус-сводка продавца (`is_active`, `current_catalog_version`, `published_product_count`, `last_published_at`), не построчный список товаров.
- `GET /api/v1/seller/catalog/template` — шаблон Excel. Не реализовано — актуальный источник шаблона (CR-001) — статическая Google-таблица, не Excel-файл через API.
- `GET /api/v1/seller/catalog/errors` — ошибки последней публикации. Не реализовано — ошибки сейчас возвращаются синхронно в ответе `POST /publications`, отдельный запрос не требовался.
```

- [ ] **Step 3: Commit**

```bash
git add docs/04-services/REST_API.md
git commit -m "REST_API.md: синхронизировать с реальным поведением (access_token, GET /publications, GET /seller/catalog)"
```

---

### Task 10: Frontend — types and API client functions

**Files:**
- Modify: `seller-cabinet/src/types.ts`
- Modify: `seller-cabinet/src/api.ts`

- [ ] **Step 1: Add response types**

In `seller-cabinet/src/types.ts`, append:

```typescript
export interface SellerStatus {
  seller_id: number
  is_active: boolean
  current_catalog_version: number
  published_product_count: number
  last_published_at: string | null
}

export interface PublicationHistoryItem {
  version: number
  published_at: string
  created: number
  updated: number
  deactivated: number
}

export interface PublicationHistoryResponse {
  publications: PublicationHistoryItem[]
}
```

- [ ] **Step 2: Add fetch functions**

In `seller-cabinet/src/api.ts`, change the import line to:

```typescript
import type {
  ApiError,
  PublicationHistoryResponse,
  PublicationRequest,
  PublicationSuccess,
  SellerStatus,
} from './types'
```

and append at the end of the file:

```typescript
export type SellerStatusResult = { ok: true; data: SellerStatus } | { ok: false; error: ApiError }
export type PublicationHistoryResult = { ok: true; data: PublicationHistoryResponse } | { ok: false; error: ApiError }

export async function fetchSellerStatus(accessToken: string): Promise<SellerStatusResult> {
  const response = await fetch(`${API_BASE}/seller/catalog?access_token=${encodeURIComponent(accessToken)}`)
  const body = await response.json()
  if (response.ok) {
    return { ok: true, data: body as SellerStatus }
  }
  return { ok: false, error: (body as { error: ApiError }).error }
}

export async function fetchPublicationHistory(accessToken: string): Promise<PublicationHistoryResult> {
  const response = await fetch(`${API_BASE}/publications?access_token=${encodeURIComponent(accessToken)}`)
  const body = await response.json()
  if (response.ok) {
    return { ok: true, data: body as PublicationHistoryResponse }
  }
  return { ok: false, error: (body as { error: ApiError }).error }
}
```

- [ ] **Step 3: Commit**

```bash
git add seller-cabinet/src/types.ts seller-cabinet/src/api.ts
git commit -m "Seller Cabinet: типы и API-клиент для статуса и истории публикаций"
```

(No automated test here — this project has no JS test infra for either frontend; Task 12 verifies everything in-browser.)

---

### Task 11: Frontend — 4-screen navigation (Главная / История / Публикация)

**Files:**
- Create: `seller-cabinet/src/PublishScreen.tsx` (extracted from current `App.tsx`)
- Create: `seller-cabinet/src/HomeScreen.tsx`
- Create: `seller-cabinet/src/HistoryScreen.tsx`
- Modify: `seller-cabinet/src/App.tsx`
- Modify: `seller-cabinet/src/index.css`

- [ ] **Step 1: Extract the existing publish form into its own component**

Create `seller-cabinet/src/PublishScreen.tsx`:

```tsx
import { useState } from 'react'
import type { FormEvent } from 'react'
import { publish } from './api'
import type { PublishResult } from './api'

type Status = 'idle' | 'loading' | 'done'

function PublishScreen({ accessToken }: { accessToken: string }) {
  const [sheetInput, setSheetInput] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PublishResult | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setStatus('loading')
    setResult(null)
    const isUrl = sheetInput.includes('/')
    const res = await publish({
      access_token: accessToken,
      ...(isUrl ? { sheet_url: sheetInput } : { spreadsheet_id: sheetInput }),
    })
    setResult(res)
    setStatus('done')
  }

  return (
    <section className="screen">
      <h1>Публикация каталога</h1>
      <p className="hint">
        Вставь <code>spreadsheet_id</code> или полную ссылку на рабочую книгу Google Sheets — сервер прочитает
        её, провалидирует и опубликует текущий каталог продавца.
      </p>

      <form className="publish-form" onSubmit={handleSubmit}>
        <label>
          Spreadsheet ID или ссылка на таблицу
          <input
            type="text"
            required
            value={sheetInput}
            onChange={(e) => setSheetInput(e.target.value)}
            placeholder="1862KR9D3PdbGp2RD1FV6m1tVmhwdcxOOdtZ0XucQjtA"
          />
        </label>
        <button type="submit" disabled={status === 'loading'}>
          {status === 'loading' ? 'Публикуем…' : 'Опубликовать'}
        </button>
      </form>

      {result && result.ok && (
        <div className="result success">
          <h2>
            Публикация выполнена успешно{' '}
            <span className={`mode-badge mode-${result.data.mode}`}>
              {result.data.mode === 'test' ? 'ТЕСТ' : 'БОЙ'}
            </span>
          </h2>
          <ul className="counts">
            <li>Создано: {result.data.created}</li>
            <li>Обновлено: {result.data.updated}</li>
            <li>Деактивировано: {result.data.deactivated}</li>
          </ul>
          <p className="publication-id">Publication ID: {result.data.publication_id}</p>
        </div>
      )}

      {result && !result.ok && (
        <div className="result error">
          <h2>Ошибка публикации ({result.error.code})</h2>
          <p>{result.error.message}</p>
          {result.error.details.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Лист</th>
                  <th>Строка</th>
                  <th>Колонка</th>
                  <th>Описание</th>
                </tr>
              </thead>
              <tbody>
                {result.error.details.map((d, i) => (
                  <tr key={i}>
                    <td>{d.sheet}</td>
                    <td>{d.row ?? '—'}</td>
                    <td>{d.column ?? '—'}</td>
                    <td>{d.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  )
}

export default PublishScreen
```

- [ ] **Step 2: Create the Home screen**

Create `seller-cabinet/src/HomeScreen.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { fetchSellerStatus } from './api'
import type { SellerStatusResult } from './api'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU')
}

function HomeScreen({ accessToken }: { accessToken: string }) {
  const [result, setResult] = useState<SellerStatusResult | null>(null)

  useEffect(() => {
    fetchSellerStatus(accessToken).then(setResult)
  }, [accessToken])

  if (result === null) {
    return (
      <section className="screen">
        <h1>Главная</h1>
        <p className="hint">Загрузка…</p>
      </section>
    )
  }

  if (!result.ok) {
    return (
      <section className="screen">
        <h1>Главная</h1>
        <div className="result error">
          <h2>Не удалось загрузить статус ({result.error.code})</h2>
          <p>{result.error.message}</p>
        </div>
      </section>
    )
  }

  const status = result.data

  return (
    <section className="screen">
      <h1>Главная</h1>
      {!status.is_active && (
        <div className="notice">Продавец ожидает активации — публикация каталога недоступна.</div>
      )}
      <div className="status-card">
        <div className="status-row">
          <span>Статус</span>
          <span>{status.is_active ? 'Активен' : 'Ожидает активации'}</span>
        </div>
        <div className="status-row">
          <span>Текущая версия каталога</span>
          <span>{status.current_catalog_version}</span>
        </div>
        <div className="status-row">
          <span>Опубликовано товаров</span>
          <span>{status.published_product_count}</span>
        </div>
        <div className="status-row">
          <span>Дата последней публикации</span>
          <span>{formatDate(status.last_published_at)}</span>
        </div>
      </div>
    </section>
  )
}

export default HomeScreen
```

- [ ] **Step 3: Create the History screen**

Create `seller-cabinet/src/HistoryScreen.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { fetchPublicationHistory } from './api'
import type { PublicationHistoryResult } from './api'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU')
}

function HistoryScreen({ accessToken }: { accessToken: string }) {
  const [result, setResult] = useState<PublicationHistoryResult | null>(null)

  useEffect(() => {
    fetchPublicationHistory(accessToken).then(setResult)
  }, [accessToken])

  if (result === null) {
    return (
      <section className="screen">
        <h1>История публикаций</h1>
        <p className="hint">Загрузка…</p>
      </section>
    )
  }

  if (!result.ok) {
    return (
      <section className="screen">
        <h1>История публикаций</h1>
        <div className="result error">
          <h2>Не удалось загрузить историю ({result.error.code})</h2>
          <p>{result.error.message}</p>
        </div>
      </section>
    )
  }

  const { publications } = result.data

  return (
    <section className="screen">
      <h1>История публикаций</h1>
      {publications.length === 0 ? (
        <p className="hint">Публикаций ещё не было.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Версия</th>
              <th>Дата</th>
              <th>Создано</th>
              <th>Обновлено</th>
              <th>Деактивировано</th>
            </tr>
          </thead>
          <tbody>
            {publications.map((p) => (
              <tr key={p.version}>
                <td>{p.version}</td>
                <td>{formatDate(p.published_at)}</td>
                <td>{p.created}</td>
                <td>{p.updated}</td>
                <td>{p.deactivated}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export default HistoryScreen
```

- [ ] **Step 4: Rewrite `App.tsx` as the navigation shell**

Replace the full contents of `seller-cabinet/src/App.tsx`:

```tsx
import { useState } from 'react'
import HistoryScreen from './HistoryScreen'
import HomeScreen from './HomeScreen'
import PublishScreen from './PublishScreen'

// Токен — единственный способ идентифицировать продавца (см. app/publication/
// seller_access.py на бэкенде): персональная ссылка вида /?token=... вместо
// открытых полей seller_id/published_by, которые раньше позволяли
// опубликовать каталог от имени любого чужого продавца.
function readAccessToken(): string | null {
  return new URLSearchParams(window.location.search).get('token')
}

type Screen = 'home' | 'history' | 'publish'

function App() {
  const [accessToken] = useState(readAccessToken)
  const [screen, setScreen] = useState<Screen>('publish')

  if (!accessToken) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">🧑‍🌾 GreenMarket — Seller Cabinet</span>
        </header>
        <main>
          <section className="screen">
            <h1>Нет доступа</h1>
            <p className="hint">
              В ссылке нет персонального токена продавца (<code>?token=…</code>). Обратитесь за своей ссылкой к
              GreenMarket — вводить чужой Seller ID вручную больше нельзя.
            </p>
          </section>
        </main>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">🧑‍🌾 GreenMarket — Seller Cabinet</span>
        <nav className="nav-tabs">
          <button className={screen === 'home' ? 'active' : ''} onClick={() => setScreen('home')}>
            Главная
          </button>
          <button className={screen === 'history' ? 'active' : ''} onClick={() => setScreen('history')}>
            История
          </button>
          <button className={screen === 'publish' ? 'active' : ''} onClick={() => setScreen('publish')}>
            Публикация
          </button>
        </nav>
      </header>

      <main>
        {screen === 'home' && <HomeScreen accessToken={accessToken} />}
        {screen === 'history' && <HistoryScreen accessToken={accessToken} />}
        {screen === 'publish' && <PublishScreen accessToken={accessToken} />}
      </main>
    </div>
  )
}

export default App
```

Note: точка входа по умолчанию остаётся «Публикация» (`screen` инициализируется `'publish'`) — не меняем уже проверенный сценарий. «Ошибки» не в нав-баре — уже отображается внутри `PublishScreen` как результат неуспешной публикации, как и раньше.

- [ ] **Step 5: Update CSS — rename `.error-table` to the shared `.data-table`, add nav/status styles**

In `seller-cabinet/src/index.css`, rename the selector (both used consistently now by `PublishScreen.tsx` and `HistoryScreen.tsx`):

```css
.data-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.75rem;
  font-size: 0.85rem;
}

.data-table th,
.data-table td {
  border: 1px solid var(--border);
  padding: 0.4rem 0.5rem;
  text-align: left;
}

.data-table th {
  background: var(--surface);
  color: var(--text);
}
```

(replaces the existing `.error-table` block — same rules, new name)

Append at the end of the file:

```css
.nav-tabs {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.6rem;
}

.nav-tabs button {
  font: inherit;
  padding: 0.35rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-muted);
  cursor: pointer;
}

.nav-tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.notice {
  background: var(--accent-bg);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  margin-bottom: 1.25rem;
}

.status-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.status-row {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem;
}

.status-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
```

- [ ] **Step 6: Build to catch type errors**

Run: `cd seller-cabinet && npm run build`
Expected: builds clean (`tsc -b && vite build`), no TypeScript errors. If `PublishScreen`/`HomeScreen`/`HistoryScreen` prop types or the `data-table` rename were missed anywhere, this step catches it.

- [ ] **Step 7: Commit**

```bash
git add seller-cabinet/src/App.tsx seller-cabinet/src/PublishScreen.tsx seller-cabinet/src/HomeScreen.tsx seller-cabinet/src/HistoryScreen.tsx seller-cabinet/src/index.css
git commit -m "Seller Cabinet: навигация на 4 экрана (Главная/История/Публикация/Ошибки)"
```

---

### Task 12: Manual browser verification

**Files:** none (verification only)

- [ ] **Step 1: Start backend + Seller Cabinet dev servers**

Use `.claude/launch.json` entries already set up for this project (`greenmarket-api` / `seller-cabinet-frontend`) via the preview tooling, or manually:

```bash
cd backend && uv run uvicorn app.main:app --reload
```
```bash
cd seller-cabinet && npm run dev
```

- [ ] **Step 2: Open Seller Cabinet with a real demo seller's token**

Navigate to `http://localhost:5174/?token=<реальный access_token одного из demo-продавцов из SELLER_ACCESS_TOKENS>`.

- [ ] **Step 3: Verify Главная**

Click "Главная". Expected: shows real status (active/version/published count/last published date) matching what's actually in the local dev DB for that seller — cross-check one number (e.g. `published_product_count`) against `SELECT COUNT(*) FROM SellerProduct WHERE seller_id=... AND is_published=TRUE`.

- [ ] **Step 4: Verify История**

Click "История". Expected: table with at least the publications already made for that demo seller in earlier sessions, newest version first, with non-zero `created`/`updated`/`deactivated` on rows published *after* this plan's migration (rows published before migration 009 will correctly show `0`/`0`/`0` — the counts didn't exist before, that's expected, not a bug).

- [ ] **Step 5: Verify Публикация still works unchanged**

Click "Публикация", run a real publish against a demo seller's Google Sheets workbook exactly as before. Expected: same success/error behavior as pre-existing, then jump back to "История" and confirm the new publication now appears at the top of the list.

- [ ] **Step 6: Verify Ошибки still triggers from a failed publish**

Trigger a validation error (e.g. a negative price row) on "Публикация" — same as existing behavior, confirm the error table (now using the renamed `.data-table` CSS class) still renders correctly.

- [ ] **Step 7: Report back**

No commit for this task — if all 6 checks pass, the plan is done. If anything fails, fix the underlying task and re-run its tests before re-verifying here.

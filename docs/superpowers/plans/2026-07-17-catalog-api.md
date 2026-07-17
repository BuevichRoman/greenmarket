# Catalog API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three read-only Catalog API endpoints (`GET /api/v1/catalog/groups`, `GET /api/v1/catalog/products`, `GET /api/v1/catalog/products/{id}`) defined in `docs/04-services/REST_API.md`, which currently exist only as a normative contract with no code — `backend/app/api/v1/` only has the Publication API.

**Architecture:** Follows the existing layered pattern (`api/v1` router → `application` use case → `infrastructure/repositories` for ORM-mapped tables + `platform/*_gateway.py` for platform-owned/unmapped tables Seller and Photo). A new `CatalogUseCase` composes existing and new repository/gateway methods to apply the offer-visibility rule already established in `docs/05-ui/Buyer_MVP.md` ("Предложения продавцов"): an offer is visible only if `Seller.is_active`, `SellerProduct.is_published`, and `Product.is_active` are all true. Pagination and sorting (`name`/`price`) happen in Python after visibility filtering, not in SQL — a deliberate Stage 1 simplification given the current catalog size (Seed Data: 15 groups / 16 products), documented inline as a thing to revisit if the catalog grows significantly.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (ORM for GreenMarket-owned tables, raw `text()` via existing gateway pattern for platform-owned/unmapped `Seller` and `Photo`), Pydantic v2, pytest against a real MySQL test database (no mocks for the DB layer — matches existing test convention).

---

## Assumptions locked in before writing this plan (confirmed with Roman, not in `REST_API.md` verbatim)

1. `GET /catalog/groups` returns a **flat list** `{id, parent_id, name, sort_order, product_count}` — not a nested tree. Client builds the tree from `parent_id`.
2. `product_count` counts only **direct** products of that group (no recursion into child groups) with ≥1 visible offer.
3. `group_id` filter on `/catalog/products` is exact match, no recursion into child groups.
4. `search` is a case-insensitive substring match on `Product.name`.
5. Sorting: `sort=name|price` (default `name`) — **not listed in `REST_API.md`'s param list**, added because `Buyer_MVP.md` §Сортировка requires it. "По популярности" is skipped — no data source exists for it (no view/sales counters anywhere in the schema), not invented.
6. When a product has multiple visible offers, the photos shown on the catalog-list tile are the photos of the **cheapest** offer (the same offer whose price is shown as `min_price`) — deterministic, tied to the displayed price.
7. `GET /catalog/products/{id}` returns **404** if the product doesn't exist, is inactive, or has zero visible offers.
8. An empty result (unknown `group_id`, no search matches) is **200 with an empty list**, not 404 — it's a filtered collection, not a missing resource.
9. Pagination: `page` (1-indexed, default 1), `limit` (default 20, max 100).

---

### Task 1: `SellerGateway.list_active_seller_ids` — bulk active-seller lookup

**Files:**
- Modify: `backend/app/platform/seller_gateway.py`
- Test: `backend/tests/test_seller_gateway.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_seller_gateway.py` (after the existing tests, same file):

```python
def test_list_active_seller_ids_returns_only_active(session):
    active_id = insert_seller(session, name="Активный продавец", publication_key=None, catalog_hash=None)
    session.execute(text("UPDATE Seller SET is_active = TRUE WHERE id = :id"), {"id": active_id})
    inactive_id = insert_seller(session, name="Неактивный продавец", publication_key=None, catalog_hash=None)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": inactive_id})

    result = SellerGateway(session).list_active_seller_ids([active_id, inactive_id])

    assert result == {active_id}


def test_list_active_seller_ids_returns_empty_set_for_empty_input(session):
    assert SellerGateway(session).list_active_seller_ids([]) == set()


def test_list_active_seller_ids_ignores_unknown_ids(session):
    active_id = insert_seller(session, name="Продавец для проверки unknown", publication_key=None, catalog_hash=None)

    result = SellerGateway(session).list_active_seller_ids([active_id, 999_999])

    assert result == {active_id}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_seller_gateway.py -v`
Expected: the 3 new tests FAIL with `AttributeError: 'SellerGateway' object has no attribute 'list_active_seller_ids'`

- [ ] **Step 3: Implement `list_active_seller_ids`**

In `backend/app/platform/seller_gateway.py`, change the import line and add the method:

```python
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session
```

Add this method to the `SellerGateway` class (after `update_current_publication`):

```python
    def list_active_seller_ids(self, seller_ids: list[int]) -> set[int]:
        if not seller_ids:
            return set()
        stmt = text("SELECT id FROM Seller WHERE id IN :seller_ids AND is_active = TRUE").bindparams(
            bindparam("seller_ids", expanding=True)
        )
        rows = self.session.execute(stmt, {"seller_ids": seller_ids}).all()
        return {row[0] for row in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_seller_gateway.py -v`
Expected: all 8 tests (5 existing + 3 new) PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/platform/seller_gateway.py backend/tests/test_seller_gateway.py docs/superpowers/plans/2026-07-17-catalog-api.md
git commit -m "Catalog API: SellerGateway.list_active_seller_ids"
```

---

### Task 2: `PhotoGateway` — new gateway for the unmapped `Photo` table

**Files:**
- Create: `backend/app/platform/photo_gateway.py`
- Test: `backend/tests/test_photo_gateway.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_photo_gateway.py`:

```python
from sqlalchemy import text

from app.platform.photo_gateway import PhotoGateway


def insert_seller_product_photo(session, *, seller_product_id: int, s3_key: str, sort_order: int) -> int:
    photo_id = session.execute(
        text("INSERT INTO Photo (s3_key) VALUES (:s3_key)"), {"s3_key": s3_key}
    ).lastrowid
    session.execute(
        text(
            "INSERT INTO SellerProductPhoto (seller_product_id, photo_id, sort_order) "
            "VALUES (:seller_product_id, :photo_id, :sort_order)"
        ),
        {"seller_product_id": seller_product_id, "photo_id": photo_id, "sort_order": sort_order},
    )
    return photo_id


def test_list_by_seller_products_returns_keys_ordered_by_sort_order(session, seller_product_id):
    insert_seller_product_photo(session, seller_product_id=seller_product_id, s3_key="b.jpg", sort_order=1)
    insert_seller_product_photo(session, seller_product_id=seller_product_id, s3_key="a.jpg", sort_order=0)

    result = PhotoGateway(session).list_by_seller_products([seller_product_id])

    assert result == {seller_product_id: ["a.jpg", "b.jpg"]}


def test_list_by_seller_products_returns_empty_dict_for_empty_input(session):
    assert PhotoGateway(session).list_by_seller_products([]) == {}


def test_list_by_seller_products_omits_seller_products_without_photos(session, seller_product_id):
    result = PhotoGateway(session).list_by_seller_products([seller_product_id])

    assert result == {}
```

This test file needs a `seller_product_id` fixture. Add it to `backend/tests/conftest.py`, which currently has no `text` import — replace `conftest.py`'s import block at the top with this complete version:

```python
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.database import SessionLocal, engine
```

Then add this fixture to `conftest.py`, right after the existing `session` fixture:

```python
@pytest.fixture
def seller_product_id(session) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": "Продавец для фото"}).lastrowid
    seller_id = session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid
    return session.execute(
        text("INSERT INTO SellerProduct (seller_id, seller_name, unit) VALUES (:seller_id, :seller_name, :unit)"),
        {"seller_id": seller_id, "seller_name": "Товар для фото", "unit": "шт"},
    ).lastrowid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_photo_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.platform.photo_gateway'`

- [ ] **Step 3: Implement `PhotoGateway`**

Create `backend/app/platform/photo_gateway.py`:

```python
from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class PhotoGateway:
    """Читает минимально необходимые платформенные данные Photo напрямую из БД.

    Photo не мапится как ORM-модель (см. app/infrastructure/models.py) — тот же
    Anti-Corruption Layer, что и SellerGateway: если источник фото сменится,
    меняется только этот файл.
    """

    def __init__(self, session: Session):
        self.session = session

    def list_by_seller_products(self, seller_product_ids: list[int]) -> dict[int, list[str]]:
        if not seller_product_ids:
            return {}
        stmt = text(
            "SELECT spp.seller_product_id, p.s3_key "
            "FROM SellerProductPhoto spp "
            "JOIN Photo p ON p.id = spp.photo_id "
            "WHERE spp.seller_product_id IN :seller_product_ids "
            "ORDER BY spp.seller_product_id, spp.sort_order"
        ).bindparams(bindparam("seller_product_ids", expanding=True))
        rows = self.session.execute(stmt, {"seller_product_ids": seller_product_ids}).all()
        result: dict[int, list[str]] = defaultdict(list)
        for seller_product_id, s3_key in rows:
            result[seller_product_id].append(s3_key)
        return dict(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_photo_gateway.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/platform/photo_gateway.py backend/tests/test_photo_gateway.py backend/tests/conftest.py
git commit -m "Catalog API: PhotoGateway"
```

---

### Task 3: `ProductGroupRepository.list_active`

**Files:**
- Modify: `backend/app/infrastructure/repositories/product_group_repository.py`
- Test: `backend/tests/test_product_group_repository.py` (new file — none existed for this repository before)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_product_group_repository.py`:

```python
from sqlalchemy import text

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository


def insert_product_group(session, *, name: str, parent_id: int | None = None, is_active: bool = True, sort_order: int = 0) -> int:
    return session.execute(
        text(
            "INSERT INTO ProductGroup (name, parent_id, is_active, sort_order) "
            "VALUES (:name, :parent_id, :is_active, :sort_order)"
        ),
        {"name": name, "parent_id": parent_id, "is_active": is_active, "sort_order": sort_order},
    ).lastrowid


def test_list_active_excludes_inactive_groups(session):
    active_id = insert_product_group(session, name="Активная группа для list_active")
    insert_product_group(session, name="Неактивная группа для list_active", is_active=False)

    result = ProductGroupRepository(session).list_active()

    ids = [g.id for g in result]
    assert active_id in ids
    assert all(g.is_active for g in result)


def test_list_active_orders_by_sort_order_then_name(session):
    insert_product_group(session, name="Z-группа sort_order test", sort_order=1)
    insert_product_group(session, name="A-группа sort_order test", sort_order=1)
    first_id = insert_product_group(session, name="Группа с sort_order 0", sort_order=0)

    result = ProductGroupRepository(session).list_active()

    assert result[0].id == first_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_product_group_repository.py -v`
Expected: FAIL with `AttributeError: 'ProductGroupRepository' object has no attribute 'list_active'`

- [ ] **Step 3: Implement `list_active`**

In `backend/app/infrastructure/repositories/product_group_repository.py`, add the method to `ProductGroupRepository`:

```python
    def list_active(self) -> list[ProductGroup]:
        return (
            self.session.query(ProductGroup)
            .filter(ProductGroup.is_active.is_(True))
            .order_by(ProductGroup.sort_order, ProductGroup.name)
            .all()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_product_group_repository.py -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/repositories/product_group_repository.py backend/tests/test_product_group_repository.py
git commit -m "Catalog API: ProductGroupRepository.list_active"
```

---

### Task 4: `ProductRepository.list_active` + `get_active`

**Files:**
- Modify: `backend/app/infrastructure/repositories/product_repository.py`
- Modify: `backend/tests/test_product_repository.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_product_repository.py` (needs a `text` import added at the top and a local insert helper — the file currently has none since it only tested read methods against seeded data):

```python
from sqlalchemy import text

from app.infrastructure.repositories.product_repository import ProductRepository


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, group_id: int, name: str, is_active: bool = True) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name, is_active) VALUES (:group_id, :name, :is_active)"),
        {"group_id": group_id, "name": name, "is_active": is_active},
    ).lastrowid


def test_list_active_excludes_inactive_products(session):
    group_id = insert_product_group(session, name="Группа для list_active")
    active_id = insert_product(session, group_id=group_id, name="Активный товар list_active")
    insert_product(session, group_id=group_id, name="Неактивный товар list_active", is_active=False)

    result = ProductRepository(session).list_active()

    ids = [p.id for p in result]
    assert active_id in ids
    assert all(p.is_active for p in result)


def test_list_active_filters_by_group_id(session):
    group_a = insert_product_group(session, name="Группа A для фильтра")
    group_b = insert_product_group(session, name="Группа B для фильтра")
    product_a = insert_product(session, group_id=group_a, name="Товар группы A")
    insert_product(session, group_id=group_b, name="Товар группы B")

    result = ProductRepository(session).list_active(group_id=group_a)

    assert [p.id for p in result] == [product_a]


def test_list_active_filters_by_search_case_insensitive(session):
    group_id = insert_product_group(session, name="Группа для поиска")
    apple_id = insert_product(session, group_id=group_id, name="Яблоко Голден")
    insert_product(session, group_id=group_id, name="Груша Конференция")

    result = ProductRepository(session).list_active(search="яблоко")

    assert [p.id for p in result] == [apple_id]


def test_get_active_returns_none_for_inactive_product(session):
    group_id = insert_product_group(session, name="Группа для get_active")
    inactive_id = insert_product(session, group_id=group_id, name="Неактивный товар get_active", is_active=False)

    assert ProductRepository(session).get_active(inactive_id) is None


def test_get_active_returns_product_for_active_product(session):
    group_id = insert_product_group(session, name="Группа для get_active 2")
    active_id = insert_product(session, group_id=group_id, name="Активный товар get_active")

    result = ProductRepository(session).get_active(active_id)

    assert result is not None
    assert result.id == active_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_product_repository.py -v`
Expected: the 5 new tests FAIL with `AttributeError: 'ProductRepository' object has no attribute 'list_active'` (or `get_active`)

- [ ] **Step 3: Implement `list_active` and `get_active`**

In `backend/app/infrastructure/repositories/product_repository.py`, add both methods to `ProductRepository`:

```python
    def list_active(self, *, group_id: int | None = None, search: str | None = None) -> list[Product]:
        query = self.session.query(Product).filter(Product.is_active.is_(True))
        if group_id is not None:
            query = query.filter(Product.product_group_id == group_id)
        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))
        return query.order_by(Product.name).all()

    def get_active(self, product_id: int) -> Product | None:
        return (
            self.session.query(Product)
            .filter(Product.id == product_id, Product.is_active.is_(True))
            .first()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_product_repository.py -v`
Expected: all tests (2 existing + 5 new) PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/repositories/product_repository.py backend/tests/test_product_repository.py
git commit -m "Catalog API: ProductRepository.list_active + get_active"
```

---

### Task 5: `SellerProductRepository.list_published_for_products`

**Files:**
- Modify: `backend/app/infrastructure/repositories/seller_product_repository.py`
- Modify: `backend/tests/test_seller_product_repository.py`

- [ ] **Step 1: Write the failing tests**

This file doesn't import `text` at module level yet. Add this import at the very top of `backend/tests/test_seller_product_repository.py`, above the existing `from app.infrastructure.repositories...` line:

```python
from sqlalchemy import text
```

Then add these tests to the file:

```python
def test_list_published_for_products_excludes_unpublished(session):
    seller_id = insert_seller(session, name="Продавец для published-фильтра")
    repository = SellerProductRepository(session)
    published = repository.create(
        seller_id=seller_id, product_id=555, seller_name="Опубликован", price=10, stock=1, unit="шт", description=None,
    )
    unpublished = repository.create(
        seller_id=seller_id, product_id=555, seller_name="Не опубликован", price=20, stock=1, unit="шт", description=None,
    )
    session.execute(
        text("UPDATE SellerProduct SET is_published = FALSE WHERE id = :id"),
        {"id": unpublished.id},
    )

    result = repository.list_published_for_products([555])

    ids = [sp.id for sp in result]
    assert published.id in ids
    assert unpublished.id not in ids


def test_list_published_for_products_filters_by_product_id(session):
    seller_id = insert_seller(session, name="Продавец для product_id-фильтра")
    repository = SellerProductRepository(session)
    for_product_a = repository.create(
        seller_id=seller_id, product_id=601, seller_name="Товар A", price=10, stock=1, unit="шт", description=None,
    )
    repository.create(
        seller_id=seller_id, product_id=602, seller_name="Товар B", price=10, stock=1, unit="шт", description=None,
    )

    result = repository.list_published_for_products([601])

    assert [sp.id for sp in result] == [for_product_a.id]


def test_list_published_for_products_returns_empty_list_for_empty_input(session):
    assert SellerProductRepository(session).list_published_for_products([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_seller_product_repository.py -v`
Expected: the 3 new tests FAIL with `AttributeError: 'SellerProductRepository' object has no attribute 'list_published_for_products'`

- [ ] **Step 3: Implement `list_published_for_products`**

In `backend/app/infrastructure/repositories/seller_product_repository.py`, add to `SellerProductRepository`:

```python
    def list_published_for_products(self, product_ids: list[int]) -> list[SellerProduct]:
        if not product_ids:
            return []
        return (
            self.session.query(SellerProduct)
            .filter(
                SellerProduct.product_id.in_(product_ids),
                SellerProduct.is_published.is_(True),
            )
            .all()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_seller_product_repository.py -v`
Expected: all tests (5 existing + 3 new) PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/repositories/seller_product_repository.py backend/tests/test_seller_product_repository.py
git commit -m "Catalog API: SellerProductRepository.list_published_for_products"
```

---

### Task 6: `catalog_schemas.py` — Pydantic response models

**Files:**
- Create: `backend/app/api/v1/catalog_schemas.py`

No dedicated test file — these are plain data-holding Pydantic models with no behavior of their own; they're exercised indirectly by the router tests in Tasks 7–9 (same convention as `backend/app/api/v1/schemas.py`, which has no `test_schemas.py`).

- [ ] **Step 1: Create the schemas file**

Create `backend/app/api/v1/catalog_schemas.py`:

```python
from decimal import Decimal

from pydantic import BaseModel


class ProductGroupItem(BaseModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int
    product_count: int


class ProductGroupsResponse(BaseModel):
    groups: list[ProductGroupItem]


class ProductListItem(BaseModel):
    id: int
    name: str
    min_price: Decimal
    offer_count: int
    photos: list[str]


class ProductListResponse(BaseModel):
    products: list[ProductListItem]
    page: int
    limit: int
    total: int


class SellerOfferItem(BaseModel):
    seller_product_id: int
    seller_id: int
    seller_name: str
    price: Decimal
    unit: str
    stock: Decimal
    description: str | None
    photos: list[str]


class ProductDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None
    offers: list[SellerOfferItem]
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd backend && python -c "from app.api.v1.catalog_schemas import ProductGroupsResponse, ProductListResponse, ProductDetailResponse; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/catalog_schemas.py
git commit -m "Catalog API: response schemas"
```

---

### Task 7: `CatalogUseCase.list_groups` + `GET /api/v1/catalog/groups`

**Files:**
- Create: `backend/app/application/catalog_use_case.py`
- Create: `backend/app/api/v1/catalog.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_catalog_use_case.py` (new)
- Test: `backend/tests/test_catalog_api.py` (new)

- [ ] **Step 1: Write the failing use-case test**

Create `backend/tests/test_catalog_use_case.py`:

```python
from sqlalchemy import text

from app.application.catalog_use_case import CatalogUseCase


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid


def insert_active_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_seller_product(session, *, seller_id: int, product_id: int, price) -> int:
    return session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец', :price, 'шт')"
        ),
        {"seller_id": seller_id, "product_id": product_id, "price": price},
    ).lastrowid


def test_list_groups_counts_only_products_with_visible_offers(session):
    group_with_offer = insert_product_group(session, name="Группа с предложением")
    group_without_offer = insert_product_group(session, name="Группа без предложений")
    product_with_offer = insert_product(session, group_id=group_with_offer, name="Товар с предложением")
    insert_product(session, group_id=group_without_offer, name="Товар без предложений")
    seller_id = insert_active_seller(session, name="Продавец для list_groups")
    insert_seller_product(session, seller_id=seller_id, product_id=product_with_offer, price=10)

    groups = {g["id"]: g for g in CatalogUseCase(session).list_groups()}

    assert groups[group_with_offer]["product_count"] == 1
    assert groups[group_without_offer]["product_count"] == 0


def test_list_groups_excludes_offers_from_inactive_sellers(session):
    group_id = insert_product_group(session, name="Группа с неактивным продавцом")
    product_id = insert_product(session, group_id=group_id, name="Товар неактивного продавца")
    seller_id = insert_active_seller(session, name="Скоро неактивный продавец")
    insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=10)
    session.execute(text("UPDATE Seller SET is_active = FALSE WHERE id = :id"), {"id": seller_id})

    groups = {g["id"]: g for g in CatalogUseCase(session).list_groups()}

    assert groups[group_id]["product_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.catalog_use_case'`

- [ ] **Step 3: Implement `CatalogUseCase` with `list_groups` only**

Create `backend/app/application/catalog_use_case.py`:

```python
from sqlalchemy.orm import Session

from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.photo_gateway import PhotoGateway
from app.platform.seller_gateway import SellerGateway


class CatalogUseCase:
    """Публичный каталог товаров для Buyer Web (см. docs/04-services/REST_API.md, Catalog API).

    Товар считается видимым только если Product.is_active, у него есть хотя бы
    одно опубликованное предложение (SellerProduct.is_published) от активного
    продавца (Seller.is_active) — см. docs/05-ui/Buyer_MVP.md, "Предложения продавцов".

    Пагинация (list_products) выполняется в памяти после фильтрации по
    видимости — сознательное упрощение Stage 1 при текущем размере каталога
    (Seed Data: 15 групп / 16 товаров). При заметном росте каталога нужно
    перенести фильтрацию/пагинацию на уровень SQL.
    """

    def __init__(self, session: Session):
        self.session = session
        self.product_group_repository = ProductGroupRepository(session)
        self.product_repository = ProductRepository(session)
        self.seller_product_repository = SellerProductRepository(session)
        self.seller_gateway = SellerGateway(session)
        self.photo_gateway = PhotoGateway(session)

    def _visible_offers_by_product(self, product_ids: list[int]) -> dict[int, list]:
        offers = self.seller_product_repository.list_published_for_products(product_ids)
        seller_ids = list({offer.seller_id for offer in offers})
        active_seller_ids = self.seller_gateway.list_active_seller_ids(seller_ids)
        by_product: dict[int, list] = {}
        for offer in offers:
            if offer.seller_id not in active_seller_ids:
                continue
            by_product.setdefault(offer.product_id, []).append(offer)
        return by_product

    def list_groups(self) -> list[dict]:
        groups = self.product_group_repository.list_active()
        products = self.product_repository.list_active()
        offers_by_product = self._visible_offers_by_product([p.id for p in products])
        visible_product_ids = set(offers_by_product.keys())

        count_by_group: dict[int, int] = {}
        for product in products:
            if product.id in visible_product_ids:
                count_by_group[product.product_group_id] = count_by_group.get(product.product_group_id, 0) + 1

        return [
            {
                "id": group.id,
                "parent_id": group.parent_id,
                "name": group.name,
                "sort_order": group.sort_order,
                "product_count": count_by_group.get(group.id, 0),
            }
            for group in groups
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: both tests PASS

- [ ] **Step 5: Write the failing router test**

Create `backend/tests/test_catalog_api.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.database import get_session
from app.main import app


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def override_session(committing_session):
    def _get_session():
        yield committing_session

    app.dependency_overrides[get_session] = _get_session


def test_get_groups_returns_seeded_groups(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера groups")
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/groups")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    ids = [g["id"] for g in body["groups"]]
    assert group_id in ids
    matching = next(g for g in body["groups"] if g["id"] == group_id)
    assert matching["product_count"] == 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: FAIL with 404 (route doesn't exist yet) — `assert 404 == 200`

- [ ] **Step 7: Create the router and register it**

Create `backend/app/api/v1/catalog.py`:

```python
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import ProductGroupItem, ProductGroupsResponse
from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/groups", response_model=ProductGroupsResponse)
def list_groups(session: Session = Depends(get_session)) -> ProductGroupsResponse:
    use_case = CatalogUseCase(session)
    groups = use_case.list_groups()
    return ProductGroupsResponse(groups=[ProductGroupItem(**group) for group in groups])
```

Modify `backend/app/main.py` — add the import and registration line:

```python
from app.api.v1.catalog import router as catalog_router
from app.api.v1.publications import router as publications_router
from app.infrastructure.database import get_session

app = FastAPI(
    title="GreenMarket Backend",
    version="1.0.0",
)
app.include_router(publications_router)
app.include_router(catalog_router)
```

(Keep the existing `from app.api.v1.publications import router as publications_router` line and `app.include_router(publications_router)` line exactly where they are — just add the two new `catalog` lines alongside them, alphabetized with the existing import.)

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && pytest tests/test_catalog_api.py tests/test_catalog_use_case.py -v`
Expected: all 3 tests PASS

- [ ] **Step 9: Run the full test suite to check nothing broke**

Run: `cd backend && pytest -v`
Expected: all tests PASS (existing + new)

- [ ] **Step 10: Commit**

```bash
git add backend/app/application/catalog_use_case.py backend/app/api/v1/catalog.py backend/app/main.py backend/tests/test_catalog_use_case.py backend/tests/test_catalog_api.py
git commit -m "Catalog API: GET /api/v1/catalog/groups"
```

---

### Task 8: `CatalogUseCase.list_products` + `GET /api/v1/catalog/products`

**Files:**
- Modify: `backend/app/application/catalog_use_case.py`
- Modify: `backend/app/api/v1/catalog.py`
- Modify: `backend/tests/test_catalog_use_case.py`
- Modify: `backend/tests/test_catalog_api.py`

- [ ] **Step 1: Write the failing use-case tests**

Add to `backend/tests/test_catalog_use_case.py` (reuse the helper functions already defined in that file from Task 7):

```python
def test_list_products_returns_min_price_and_offer_count(session):
    group_id = insert_product_group(session, name="Группа для min_price")
    product_id = insert_product(session, group_id=group_id, name="Товар с двумя предложениями")
    seller_a = insert_active_seller(session, name="Продавец подороже")
    seller_b = insert_active_seller(session, name="Продавец подешевле")
    insert_seller_product(session, seller_id=seller_a, product_id=product_id, price=100)
    insert_seller_product(session, seller_id=seller_b, product_id=product_id, price=50)

    items, total = CatalogUseCase(session).list_products()

    item = next(i for i in items if i["id"] == product_id)
    assert item["min_price"] == 50
    assert item["offer_count"] == 2
    assert total >= 1


def test_list_products_excludes_products_without_visible_offers(session):
    group_id = insert_product_group(session, name="Группа без видимых товаров")
    product_id = insert_product(session, group_id=group_id, name="Товар без предложений list_products")

    items, _ = CatalogUseCase(session).list_products()

    assert product_id not in [i["id"] for i in items]


def test_list_products_filters_by_group_id(session):
    group_a = insert_product_group(session, name="Группа A для list_products фильтра")
    group_b = insert_product_group(session, name="Группа B для list_products фильтра")
    product_a = insert_product(session, group_id=group_a, name="Товар группы A list_products")
    product_b = insert_product(session, group_id=group_b, name="Товар группы B list_products")
    seller_id = insert_active_seller(session, name="Продавец для группового фильтра")
    insert_seller_product(session, seller_id=seller_id, product_id=product_a, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=product_b, price=10)

    items, _ = CatalogUseCase(session).list_products(group_id=group_a)

    ids = [i["id"] for i in items]
    assert product_a in ids
    assert product_b not in ids


def test_list_products_filters_by_search(session):
    group_id = insert_product_group(session, name="Группа для поиска list_products")
    apple_id = insert_product(session, group_id=group_id, name="Яблоко Симиренко")
    pear_id = insert_product(session, group_id=group_id, name="Груша Дюшес")
    seller_id = insert_active_seller(session, name="Продавец для поиска list_products")
    insert_seller_product(session, seller_id=seller_id, product_id=apple_id, price=10)
    insert_seller_product(session, seller_id=seller_id, product_id=pear_id, price=10)

    items, _ = CatalogUseCase(session).list_products(search="яблоко")

    ids = [i["id"] for i in items]
    assert apple_id in ids
    assert pear_id not in ids


def test_list_products_sorts_by_price_when_requested(session):
    group_id = insert_product_group(session, name="Группа для сортировки по цене")
    cheap_id = insert_product(session, group_id=group_id, name="Дешёвый товар sort")
    expensive_id = insert_product(session, group_id=group_id, name="Дорогой товар sort")
    seller_id = insert_active_seller(session, name="Продавец для сортировки")
    insert_seller_product(session, seller_id=seller_id, product_id=cheap_id, price=5)
    insert_seller_product(session, seller_id=seller_id, product_id=expensive_id, price=500)

    items, _ = CatalogUseCase(session).list_products(sort="price", group_id=group_id)

    assert [i["id"] for i in items] == [cheap_id, expensive_id]


def test_list_products_paginates(session):
    group_id = insert_product_group(session, name="Группа для пагинации")
    seller_id = insert_active_seller(session, name="Продавец для пагинации")
    product_ids = []
    for i in range(3):
        pid = insert_product(session, group_id=group_id, name=f"Товар пагинации {i}")
        insert_seller_product(session, seller_id=seller_id, product_id=pid, price=10)
        product_ids.append(pid)

    page_1, total = CatalogUseCase(session).list_products(group_id=group_id, page=1, limit=2)
    page_2, _ = CatalogUseCase(session).list_products(group_id=group_id, page=2, limit=2)

    assert total == 3
    assert len(page_1) == 2
    assert len(page_2) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: the 6 new tests FAIL with `TypeError: CatalogUseCase.list_products() missing` or `AttributeError`

- [ ] **Step 3: Implement `list_products`**

Add to `CatalogUseCase` in `backend/app/application/catalog_use_case.py` (after `list_groups`):

```python
    def list_products(
        self,
        *,
        group_id: int | None = None,
        search: str | None = None,
        sort: str = "name",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        products = self.product_repository.list_active(group_id=group_id, search=search)
        offers_by_product = self._visible_offers_by_product([p.id for p in products])
        visible_products = [p for p in products if p.id in offers_by_product]

        cheapest_offer_by_product = {
            product_id: min(offers, key=lambda o: o.price)
            for product_id, offers in offers_by_product.items()
        }

        if sort == "price":
            visible_products.sort(key=lambda p: cheapest_offer_by_product[p.id].price)
        else:
            visible_products.sort(key=lambda p: p.name)

        total = len(visible_products)
        start = (page - 1) * limit
        page_items = visible_products[start : start + limit]

        cheapest_offer_ids = [cheapest_offer_by_product[p.id].id for p in page_items]
        photos_by_seller_product = self.photo_gateway.list_by_seller_products(cheapest_offer_ids)

        items = []
        for product in page_items:
            offers = offers_by_product[product.id]
            cheapest = cheapest_offer_by_product[product.id]
            items.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "min_price": cheapest.price,
                    "offer_count": len(offers),
                    "photos": photos_by_seller_product.get(cheapest.id, []),
                }
            )
        return items, total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: all tests PASS

- [ ] **Step 5: Write the failing router tests**

Add to `backend/tests/test_catalog_api.py`:

```python
def insert_product(session, *, group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": group_id, "name": name},
    ).lastrowid


def insert_active_seller(session, *, name: str) -> int:
    user_id = session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid
    return session.execute(text("INSERT INTO Seller (user_id) VALUES (:user_id)"), {"user_id": user_id}).lastrowid


def insert_seller_product(session, *, seller_id: int, product_id: int, price) -> int:
    return session.execute(
        text(
            "INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, unit) "
            "VALUES (:seller_id, :product_id, 'Тестовый продавец роутера', :price, 'шт')"
        ),
        {"seller_id": seller_id, "product_id": product_id, "price": price},
    ).lastrowid


def test_get_products_returns_visible_product_with_min_price(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера products")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар для роутера products")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера products")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=42)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products?group_id={group_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    item = next(i for i in body["products"] if i["id"] == product_id)
    assert item["min_price"] == "42"
    assert item["offer_count"] == 1
    assert body["page"] == 1
    assert body["limit"] == 20


def test_get_products_rejects_invalid_limit(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products?limit=0")

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: the 2 new tests FAIL with 404 (route doesn't exist)

- [ ] **Step 7: Add the endpoint**

Modify `backend/app/api/v1/catalog.py` — replace the entire import block at the top of the file with this complete version:

```python
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import (
    ProductGroupItem,
    ProductGroupsResponse,
    ProductListItem,
    ProductListResponse,
)
from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
```

(This replaces every `import`/`from` line plus the `logger`/`router` declarations from Task 7 — the `list_groups` function definition below stays untouched.)

Add after `list_groups`:

```python
@router.get("/products", response_model=ProductListResponse)
def list_products(
    group_id: int | None = None,
    search: str | None = None,
    sort: Literal["name", "price"] = "name",
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> ProductListResponse:
    use_case = CatalogUseCase(session)
    items, total = use_case.list_products(group_id=group_id, search=search, sort=sort, page=page, limit=limit)
    return ProductListResponse(
        products=[ProductListItem(**item) for item in items],
        page=page,
        limit=limit,
        total=total,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: all tests PASS

- [ ] **Step 9: Run the full test suite**

Run: `cd backend && pytest -v`
Expected: all tests PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/application/catalog_use_case.py backend/app/api/v1/catalog.py backend/tests/test_catalog_use_case.py backend/tests/test_catalog_api.py
git commit -m "Catalog API: GET /api/v1/catalog/products"
```

---

### Task 9: `CatalogUseCase.get_product` + `GET /api/v1/catalog/products/{product_id}`

**Files:**
- Modify: `backend/app/application/catalog_use_case.py`
- Modify: `backend/app/api/v1/catalog.py`
- Modify: `backend/tests/test_catalog_use_case.py`
- Modify: `backend/tests/test_catalog_api.py`

- [ ] **Step 1: Write the failing use-case tests**

Add to `backend/tests/test_catalog_use_case.py`:

```python
def test_get_product_returns_offers_sorted_by_price(session):
    group_id = insert_product_group(session, name="Группа для get_product")
    product_id = insert_product(session, group_id=group_id, name="Товар для get_product")
    seller_expensive = insert_active_seller(session, name="Дорогой продавец get_product")
    seller_cheap = insert_active_seller(session, name="Дешёвый продавец get_product")
    insert_seller_product(session, seller_id=seller_expensive, product_id=product_id, price=200)
    insert_seller_product(session, seller_id=seller_cheap, product_id=product_id, price=20)

    result = CatalogUseCase(session).get_product(product_id)

    assert result is not None
    assert result["id"] == product_id
    assert [offer["price"] for offer in result["offers"]] == [20, 200]


def test_get_product_returns_none_for_product_without_visible_offers(session):
    group_id = insert_product_group(session, name="Группа для get_product без предложений")
    product_id = insert_product(session, group_id=group_id, name="Товар без предложений get_product")

    assert CatalogUseCase(session).get_product(product_id) is None


def test_get_product_returns_none_for_missing_product(session):
    assert CatalogUseCase(session).get_product(999_999) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: the 3 new tests FAIL with `AttributeError: 'CatalogUseCase' object has no attribute 'get_product'`

- [ ] **Step 3: Implement `get_product`**

Add to `CatalogUseCase` in `backend/app/application/catalog_use_case.py` (after `list_products`):

```python
    def get_product(self, product_id: int) -> dict | None:
        product = self.product_repository.get_active(product_id)
        if product is None:
            return None

        offers_by_product = self._visible_offers_by_product([product_id])
        offers = offers_by_product.get(product_id, [])
        if not offers:
            return None

        offers_sorted = sorted(offers, key=lambda o: o.price)
        offer_ids = [offer.id for offer in offers_sorted]
        photos_by_seller_product = self.photo_gateway.list_by_seller_products(offer_ids)

        return {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "offers": [
                {
                    "seller_product_id": offer.id,
                    "seller_id": offer.seller_id,
                    "seller_name": offer.seller_name,
                    "price": offer.price,
                    "unit": offer.unit,
                    "stock": offer.stock,
                    "description": offer.description,
                    "photos": photos_by_seller_product.get(offer.id, []),
                }
                for offer in offers_sorted
            ],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_use_case.py -v`
Expected: all tests PASS

- [ ] **Step 5: Write the failing router tests**

Add to `backend/tests/test_catalog_api.py`:

```python
def test_get_product_by_id_returns_offers(committing_session):
    group_id = insert_product_group(committing_session, name="Группа для роутера product detail")
    product_id = insert_product(committing_session, group_id=group_id, name="Товар для роутера detail")
    seller_id = insert_active_seller(committing_session, name="Продавец для роутера detail")
    insert_seller_product(committing_session, seller_id=seller_id, product_id=product_id, price=15)
    override_session(committing_session)
    client = TestClient(app)

    response = client.get(f"/api/v1/catalog/products/{product_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == product_id
    assert len(body["offers"]) == 1
    assert body["offers"][0]["price"] == "15"


def test_get_product_by_id_returns_404_for_missing_product(committing_session):
    override_session(committing_session)
    client = TestClient(app)

    response = client.get("/api/v1/catalog/products/999999")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: the 2 new tests FAIL — `/products/{product_id}` isn't routed yet (FastAPI would 404 on an unmatched path, or match `/products` collection route incorrectly depending on order; either way the new assertions on response body fail)

- [ ] **Step 7: Add the endpoint**

Modify `backend/app/api/v1/catalog.py` — replace the entire import block at the top of the file with this complete final version:

```python
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.catalog_schemas import (
    ProductDetailResponse,
    ProductGroupItem,
    ProductGroupsResponse,
    ProductListItem,
    ProductListResponse,
    SellerOfferItem,
)
from app.api.v1.schemas import ErrorDetail, ErrorResponse
from app.application.catalog_use_case import CatalogUseCase
from app.infrastructure.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
```

(This replaces every `import`/`from` line plus the `logger`/`router` declarations at the top of the file — the `list_groups` and `list_products` function definitions below stay untouched.)

Add after `list_products`:

```python
def _not_found(message: str) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code="NOT_FOUND", message=message, details=[]))
    return JSONResponse(status_code=404, content=payload.model_dump())


@router.get("/products/{product_id}")
def get_product(product_id: int, session: Session = Depends(get_session)):
    use_case = CatalogUseCase(session)
    product = use_case.get_product(product_id)
    if product is None:
        return _not_found(f"Товар {product_id} не найден или недоступен")
    return ProductDetailResponse(
        id=product["id"],
        name=product["name"],
        description=product["description"],
        offers=[SellerOfferItem(**offer) for offer in product["offers"]],
    )
```

Important: this route (`/products/{product_id}`) must be registered **after** `/products` in the file — FastAPI matches routes in declaration order, and a `{product_id}` path parameter would otherwise shadow nothing here since `/products` (no trailing segment) and `/products/{product_id}` don't actually collide, but keep this endpoint below `list_products` in the file for readability or the code above is applied ok either order structurally. No change needed if you added it after `list_products` as instructed above.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_catalog_api.py -v`
Expected: all tests PASS

- [ ] **Step 9: Run the full test suite**

Run: `cd backend && pytest -v`
Expected: all tests PASS — this is the full Catalog API, done

- [ ] **Step 10: Commit**

```bash
git add backend/app/application/catalog_use_case.py backend/app/api/v1/catalog.py backend/tests/test_catalog_use_case.py backend/tests/test_catalog_api.py
git commit -m "Catalog API: GET /api/v1/catalog/products/{id}"
```

---

## Self-review notes

- **Spec coverage:** all 3 `REST_API.md` Catalog API endpoints implemented (Tasks 7–9); all 9 locked-in assumptions from the top of this plan are reflected in the code (flat group list, direct-only counts/filter, case-insensitive search, `sort` param with `price`/`name` only, cheapest-offer photo tie-break, 404 rules, empty-result-is-200, pagination defaults).
- **Not in scope, deliberately:** "последние опубликованные товары" on the Главная screen (not part of the 3 `REST_API.md` Catalog API endpoints, no task for it); "по популярности" sort (no data source); recursive group-subtree rollup for counts/filtering (assumption #2/#3 says direct-only).
- **Known follow-up, not blocking:** in-memory pagination is a Stage-1-scale simplification, documented in `CatalogUseCase`'s docstring, not silently left unexplained.

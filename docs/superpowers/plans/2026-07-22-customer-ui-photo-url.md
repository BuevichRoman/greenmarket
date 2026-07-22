# Customer UI — фото товара: фикс URL (цикл 3/3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catalog API (`GET /api/v1/catalog/products`, `GET /api/v1/catalog/products/{id}`) должен отдавать в поле `photos` полный публичный URL фото, а не сырой `s3_key`, чтобы `<img src>` в buyer-web реально грузил картинку.

**Architecture:** Единственная точка изменения — `CatalogUseCase` (`backend/app/application/catalog_use_case.py`). Добавляется module-level helper `_photo_urls()`, оборачивающий уже существующую `build_photo_url()` (`app/platform/photo_storage.py`) — тот же паттерн, что уже используется в `app/api/v1/photos.py`. Никакого нового DI, никаких изменений в `PhotoGateway` или во frontend.

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, pytest.

**Design doc:** `docs/superpowers/specs/2026-07-22-customer-ui-photo-url-design.md`

---

### Task 1: `_photo_urls()` helper + wiring в `list_products`/`get_product`

**Files:**
- Modify: `backend/app/application/catalog_use_case.py`
- Test: `backend/tests/test_catalog_use_case.py`

- [ ] **Step 1: Обновить существующий тест `list_products`, чтобы он ожидал полный URL**

Открыть `backend/tests/test_catalog_use_case.py`. Добавить в начало файла (после существующего `from sqlalchemy import text`) два импорта:

```python
from app.core.config import settings
from app.platform.photo_storage import build_photo_url
```

Файл целиком после правки импортов (строки 1-4):

```python
from sqlalchemy import text

from app.application.catalog_use_case import CatalogUseCase
from app.core.config import settings
from app.platform.photo_storage import build_photo_url
```

Затем заменить последнюю строку теста `test_list_products_breaks_price_ties_deterministically_for_cheapest_offer` (сейчас строка 206):

```python
    assert item["photos"] == ["lower.jpg"]
```

на:

```python
    assert item["photos"] == [build_photo_url("lower.jpg", bucket=settings.s3_bucket, region=settings.s3_region)]
```

- [ ] **Step 2: Добавить новый тест на `get_product`, покрывающий фото предложения**

Добавить в конец файла `backend/tests/test_catalog_use_case.py` (после определения `insert_seller_product_photo`, то есть в самый конец файла) новую тестовую функцию:

```python
def test_get_product_returns_photo_urls_for_offer(session):
    group_id = insert_product_group(session, name="Группа для get_product фото")
    product_id = insert_product(session, group_id=group_id, name="Товар для get_product фото")
    seller_id = insert_active_seller(session, name="Продавец для get_product фото")
    offer_id = insert_seller_product(session, seller_id=seller_id, product_id=product_id, price=15)
    insert_seller_product_photo(session, seller_product_id=offer_id, s3_key="offer.jpg")

    result = CatalogUseCase(session).get_product(product_id)

    expected_url = build_photo_url("offer.jpg", bucket=settings.s3_bucket, region=settings.s3_region)
    assert result["offers"][0]["photos"] == [expected_url]
```

- [ ] **Step 3: Запустить тесты, убедиться что оба падают**

Run: `cd backend && uv run pytest tests/test_catalog_use_case.py -v`

Expected: `test_list_products_breaks_price_ties_deterministically_for_cheapest_offer` FAIL (`assert ['lower.jpg'] == ['https://...lower.jpg']` или похожая ошибка), `test_get_product_returns_photo_urls_for_offer` FAIL (`assert ['offer.jpg'] == [...]` либо `KeyError`/`AssertionError` на `photos`). Оба падают именно на сравнении `photos`, не на других причинах (например `ImportError`) — если импорт `settings`/`build_photo_url` не находится, значит опечатка в пути импорта, поправить перед продолжением.

- [ ] **Step 4: Реализовать `_photo_urls()` и подключить в обоих местах**

Открыть `backend/app/application/catalog_use_case.py`. Изменить блок импортов (строки 1-7):

```python
from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import build_photo_url
from app.platform.seller_gateway import SellerGateway


def _photo_urls(s3_keys: list[str]) -> list[str]:
    return [build_photo_url(key, bucket=settings.s3_bucket, region=settings.s3_region) for key in s3_keys]
```

Затем в методе `list_products()` заменить строку (сейчас строка 104):

```python
                    "photos": photos_by_seller_product.get(cheapest.id, []),
```

на:

```python
                    "photos": _photo_urls(photos_by_seller_product.get(cheapest.id, [])),
```

И в методе `get_product()` заменить строку (сейчас строка 136):

```python
                    "photos": photos_by_seller_product.get(offer.id, []),
```

на:

```python
                    "photos": _photo_urls(photos_by_seller_product.get(offer.id, [])),
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `cd backend && uv run pytest tests/test_catalog_use_case.py -v`
Expected: PASS — все тесты файла зелёные, включая оба изменённых/новых.

- [ ] **Step 6: Прогнать весь backend test suite (регрессия)**

Run: `cd backend && uv run pytest`
Expected: PASS, 0 failed. Это тот же suite, который был 246/246 зелёным до цикла 3 — теперь на 1 тест больше (247), все зелёные. Если что-то другое сломалось — не относящееся к `catalog_use_case.py`/`photos` изменение, разобраться перед коммитом.

- [ ] **Step 7: Commit**

```bash
git add backend/app/application/catalog_use_case.py backend/tests/test_catalog_use_case.py
git commit -m "GreenMarket: Catalog API отдаёт полный URL фото вместо сырого s3_key"
```

---

## После выполнения плана

Обе задачи design-документа («вне объёма») остаются: настройка S3 public-read/AWS credentials и деплой — это отдельный шаг после мержа всего `worktree-photo-upload-backend` (циклы 1+2+3) в `main`, не часть этого плана.

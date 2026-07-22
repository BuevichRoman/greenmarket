# Design: Customer UI — фото товара (цикл 3 из 3 — карточка товара продавца)

**Дата:** 2026-07-22
**Статус:** Approved (Roman), design для внутренней реализации — узкий scope, без доп. фич (галерея на несколько фото, лайтбокс отклонены на этапе брейнсторминга).

## Контекст

Разведка при дизайне цикла 1 (`docs/superpowers/specs/2026-07-21-photo-upload-backend-design.md`) предположила, что цикл 3 (Customer UI) будет «почти бесплатным»: `buyer-web` уже принимает `photos: string[]`, Catalog API уже отдаёт это поле. Проверка перед стартом цикла 3 подтвердила гипотезу с одним уточнением, которое и есть содержание этого цикла.

`buyer-web` (`ProductCard.tsx`, `OfferCard.tsx`, `PhotoPlaceholder.tsx`) уже полностью готов: рендерит `photos[0]` как `<img src=...>`, с фолбэком на плейсхолдер при пустом списке. Изменений на фронтенде не требуется.

Единственный реальный пробел — на backend. `CatalogUseCase.list_products()`/`get_product()` (`backend/app/application/catalog_use_case.py:104,136`) отдают наружу сырой `s3_key` (например `seller-products/uuid.jpg`) вместо публичного URL. Функция `build_photo_url()` для этого уже существует (`backend/app/platform/photo_storage.py:36`) и используется в seller-facing `GET /api/v1/photos` (`backend/app/api/v1/photos.py:87`), но не подключена в Catalog API — из-за этого `<img src>` в buyer-web получал бы нерабочую ссылку.

## Scope

**В объём:**
- `catalog_use_case.py`: конвертация каждого `s3_key` в полный URL через `build_photo_url(s3_key, bucket=settings.s3_bucket, region=settings.s3_region)` — в обоих местах, где формируется `"photos"` (`list_products` и `get_product`). Импорт `settings` напрямую из `app.core.config`, тот же паттерн, что уже используется в `photos.py` (без нового DI-параметра в конструкторе `CatalogUseCase`).
- Обновление `tests/test_catalog_use_case.py` — единственный тест, проверяющий поле `photos` (`test_list_products_breaks_price_ties_deterministically_for_cheapest_offer`, строка 206), должен сравнивать с результатом `build_photo_url(...)`, а не с сырым `"lower.jpg"` — так тест не задваивает формат URL и не расходится с продакшн-кодом при будущих правках `build_photo_url`.

**Вне объёма (сознательно):**
- Любые изменения `buyer-web` — компоненты уже готовы принимать URL.
- Галерея из нескольких фото / лайтбокс на `ProductScreen` — отклонено пользователем при брейнсторминге, не нужно для Stage 1 (сейчас показывается только `photos[0]`, как и раньше).
- Настройка S3-бакета (public-read) и AWS-креды — инфраструктурная задача вне кода. Без неё URL будет корректно сформирован, но фото не откроется в браузере (403/timeout) — чек-лист для Романа перед прод-верификацией, не блокирует код/тесты цикла 3.
- Деплой в прод и скриншоты карточки продавца для коллеги — по решению Романа делаются после мержа этого цикла, отдельным шагом (не часть этого design).

## Backend

```python
# app/application/catalog_use_case.py
from app.core.config import settings
from app.platform.photo_storage import build_photo_url

def _photo_urls(s3_keys: list[str]) -> list[str]:
    return [build_photo_url(key, bucket=settings.s3_bucket, region=settings.s3_region) for key in s3_keys]
```

Применяется в двух местах, заменяя прямой `photos_by_seller_product.get(..., [])`:
- `list_products()`, строка `"photos": photos_by_seller_product.get(cheapest.id, [])` → `"photos": _photo_urls(photos_by_seller_product.get(cheapest.id, []))`
- `get_product()`, строка `"photos": photos_by_seller_product.get(offer.id, [])` → `"photos": _photo_urls(photos_by_seller_product.get(offer.id, []))`

Свободная функция на уровне модуля (не метод класса) — не требует `self`, не завязана на состояние `CatalogUseCase`, симметрична с тем, как `build_photo_url` уже используется как чистая функция в `photos.py`.

## Тесты

Правка одного assert в `tests/test_catalog_use_case.py`:

```python
from app.core.config import settings
from app.platform.photo_storage import build_photo_url
...
expected_url = build_photo_url("lower.jpg", bucket=settings.s3_bucket, region=settings.s3_region)
assert item["photos"] == [expected_url]
```

Новых тестовых файлов не требуется — покрытие уже существует, меняется только ожидаемое значение.

## После цикла 3 (вне кода)

1. Мердж `worktree-photo-upload-backend` (циклы 1+2+3) в `main`, push в origin.
2. Прод-деплой backend + `buyer-web` на `104.171.133.95`.
3. Прежде чем фото реально откроются — Роман проверяет/настраивает S3 public-read + AWS credentials (не сделано ни локально, ни на прод-сервере на момент этого design).
4. Скриншоты карточки продавца («снаружи» и «изнутри») для коллеги — отдельным шагом после деплоя, требует реального деплоя Apps Script в тестовую Google-таблицу через живой Chrome/Google-аккаунт Романа.

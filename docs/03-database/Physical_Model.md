# GreenMarket Physical Data Model

**Version:** 1.0
**Status:** Normative

## Назначение

Настоящий документ определяет физическую модель базы данных GreenMarket Stage 1. Документ является основой для SQL DDL, миграций, REST API и Publication Service. Все таблицы и связи первого этапа должны соответствовать данной модели.

## Общая структура

Подсистема каталога состоит из следующих сущностей.

Платформенная таблица (существует на платформе, не создаётся заново): `users` (в БД `aristotel_taxi`). Отдельной таблицы User в GreenMarket нет — поля `moderator_id` (SellerProduct) и `published_by` (CatalogPublication) ссылаются напрямую на `users.id_user`.

Новые таблицы GreenMarket: ProductGroup, Product, Seller, Photo, SellerProduct, SellerProductPhoto, CatalogPublication.

## Общая схема

```text
Seller
│
│1
│
├──────────────┐
│              │
│N             │N
▼              ▼
SellerProduct   CatalogPublication
│
│N
│
▼
Product
│
│N
▼
ProductGroup

SellerProduct
│
│N
▼
SellerProductPhoto
│
│N
▼
Photo
```

## ProductGroup

**Назначение:** хранит дерево товарных групп платформы.

**Основные поля:** `id`, `parent_id`, `name`, `sort_order`, `is_active`, `created_at`, `updated_at`.

**Особенности:** древовидная структура (самоссылка `parent_id`); коммерческие данные отсутствуют; изменение выполняется только администраторами.

## Product

**Назначение:** единый справочник товаров GreenMarket.

**Основные поля:** `id`, `product_group_id`, `name`, `description`, `is_active`, `created_at`, `updated_at`.

**Особенности:** одна запись соответствует одному товару; используется всеми продавцами; не содержит коммерческих характеристик.

## SellerProduct

**Назначение:** предложение конкретного продавца. Основная рабочая таблица подсистемы — `id` этой таблицы одновременно является `SellerProductId`, постоянным техническим идентификатором позиции в рабочем каталоге продавца (см. [Catalog_Template.md](../02-domain/Catalog_Template.md)).

**Основные поля:** `id`, `seller_id`, `product_id` (NULL допускается до модерации), `seller_name`, `unit`, `price`, `stock`, `description`, `is_published`, `moderation_status`, `moderator_id`, `moderated_at`, `moderation_comment`, `created_at`, `updated_at`.

**Значения `moderation_status`:** `WAIT_PRODUCT` (товар без связи с Product, ожидает модерации), `IN_PROGRESS` (модерация начата), `RESOLVED` (модерация завершена).

**Особенности:** принадлежит одному продавцу; содержит коммерческие данные; создаётся Publication Service; физически не удаляется.

## SellerProductPhoto

**Назначение:** связь SellerProduct с фотографиями.

**Основные поля:** `seller_product_id`, `photo_id`, `sort_order`.

**Особенности:** поддерживает несколько фотографий; определяет порядок отображения.

## CatalogPublication

**Назначение:** журнал публикаций каталога продавца.

**Основные поля:** `id`, `seller_id`, `version`, `publication_key`, `catalog_hash`, `published_at`, `published_by`.

**Особенности:** запись создаётся при каждой успешной публикации; изменение существующих записей запрещено; удаление запрещено.

## Seller

**Назначение:** техническая учётная запись продавца GreenMarket и хранение текущего состояния опубликованного каталога. История публикаций хранится исключительно в CatalogPublication.

**Основные поля:** `id`, `user_id` (ссылка на `users.id_user` платформенной БД, связь 1:1), `is_active`, `created_at`, `updated_at`, `current_catalog_version`, `current_publication_key`, `current_catalog_hash`.

**Особенности:** новая таблица GreenMarket, не изменяет платформенную `users`; отделяет специфичное для продавца состояние публикации от учётной записи пользователя платформы.

## Photo

**Назначение:** метаданные фотографий товаров продавцов. Временное решение Stage 1 — сами файлы хранятся в S3, таблица хранит только ключ объекта.

**Основные поля:** `id`, `s3_key`, `created_at`.

**Особенности:** новая таблица GreenMarket; физическое удаление не запрещено (в отличие от бизнес-сущностей каталога) — неиспользуемые фото может очищать отдельный сервис обслуживания.

## Основные связи

| Связь | Кардинальность |
|---|---|
| ProductGroup → Product | один ко многим |
| Seller → SellerProduct | один ко многим |
| Product → SellerProduct | один ко многим (несколько продавцов публикуют один Product) |
| SellerProduct → SellerProductPhoto | один ко многим |
| Photo → SellerProductPhoto | один ко многим |
| Seller → CatalogPublication | один ко многим |

## Ограничения модели

Физическое удаление не используется для Product, SellerProduct, CatalogPublication. Для прекращения использования применяются логические признаки активности и публикации (`is_active`, `is_published`).

## Владение данными

| Таблица | Владелец |
|---|---|
| ProductGroup | Admin |
| Product | Admin |
| SellerProduct | Publication Service |
| SellerProductPhoto | Publication Service |
| CatalogPublication | Publication Service |
| Seller | Platform |
| Photo | Publication Service |

## Основные принципы

Физическая модель строится на следующих принципах.

- Единый каталог отделён от каталогов продавцов.
- История публикаций отделена от текущего состояния.
- Product не содержит коммерческих данных.
- Все коммерческие характеристики принадлежат SellerProduct.
- Publication Service является единственным владельцем изменений рабочего каталога.
- Все операции публикации выполняются одной транзакцией.

## Связь с другими документами

Настоящий документ определяет физическую модель данных. SQL-реализация определяется документом [DDL_Specification.md](DDL_Specification.md). Правила проектирования схемы определяются документом [Coding_Standard.md](Coding_Standard.md). Порядок создания объектов базы данных определяется документом [Database_Migrations.md](Database_Migrations.md) и файлами в [`../../database/migrations/`](../../database/migrations/).

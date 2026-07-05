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

- `POST /api/v1/publications` — создание публикации (Excel-файл + `publication_key`). Ответ: идентификатор публикации, результат проверки.
- `GET /api/v1/publications/{id}` — состояние публикации: статус, ошибки, дата создания.
- `GET /api/v1/publications` — история публикаций продавца.

## Seller API

Используется Seller Cabinet.

- `GET /api/v1/seller/catalog` — текущий каталог.
- `GET /api/v1/seller/catalog/template` — шаблон Excel.
- `GET /api/v1/seller/catalog/errors` — ошибки последней публикации.

## Admin API

Используется Admin Cabinet.

- `GET/POST /api/v1/admin/product-groups`, `PUT /api/v1/admin/product-groups/{id}` — управление ProductGroup.
- `GET/POST /api/v1/admin/products`, `PUT /api/v1/admin/products/{id}` — управление Product.
- `GET /api/v1/admin/sellers`, `PUT /api/v1/admin/sellers/{id}/activate`, `PUT /api/v1/admin/sellers/{id}/deactivate` — управление продавцами.
- `GET /api/v1/admin/moderation`, `PUT /api/v1/admin/moderation/{id}` — очередь модерации (обработка SellerProduct без связи с Product).

## System API

- `GET /api/v1/health` — проверка работоспособности. Ответ: `{"status": "ok"}`.

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

Предметная модель определяется документом [Domain_Model.md](../02-domain/Domain_Model.md). Процесс публикации определяется документом [Publication_Service.md](Publication_Service.md). Конечный автомат публикации определяется документом [Publication_FSM.md](Publication_FSM.md). Пользовательские сценарии определяются документами [Buyer_MVP.md](../05-ui/Buyer_MVP.md), [Seller_MVP.md](../05-ui/Seller_MVP.md) и [Admin_MVP.md](../05-ui/Admin_MVP.md).

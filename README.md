# GreenMarket Stage 1 Documentation

**Version:** 1.0
**Status:** Normative

## Назначение

GreenMarket — цифровая платформа для публикации и поиска товаров локальных продавцов. Настоящая документация описывает первый этап проекта (Stage 1) целиком: архитектуру, модель данных, сервисы, пользовательские интерфейсы, инфраструктуру и правила разработки — создание единого цифрового каталога рынка и проверку его работоспособности на реальных продавцах и покупателях.

Документация **нормативна** — используется как основание для реализации системы.

## Порядок чтения

```text
README
  │
  ▼
Vision → Scope → Roadmap        (docs/00-overview, docs/01-overview)
  │
  ▼
Domain Model → Catalog Model → Publication Model → Catalog Template   (docs/02-domain)
  │
  ▼
Database                        (docs/03-database)
  │
  ▼
Services                        (docs/04-services)
  │
  ▼
UI                               (docs/05-ui)
  │
  ▼
Development                     (docs/06-development)
```

Новый разработчик читает документацию именно в этом порядке — от целей проекта к модели данных, затем к сервисам, интерфейсам и правилам разработки.

## Контекст платформы

GreenMarket реализуется поверх существующей платформы **iBronevik** и переиспользует её сущности: `Seller`, `User`, `Photo`, `Organization`, `Address`. Подсистема каталога первого этапа добавляет только пять новых таблиц (`ProductGroup`, `Product`, `SellerProduct`, `SellerProductPhoto`, `CatalogPublication`) и три новых поля `Seller` — см. [docs/03-database/Physical_Model.md](docs/03-database/Physical_Model.md).

## Цели первого этапа

1. Создать единый каталог товаров GreenMarket.
2. Предоставить продавцам максимально простой способ публикации своих каталогов.
3. Предоставить покупателям единый каталог товаров всех продавцов.
4. Проверить жизнеспособность бизнес-модели на реальных данных.

Первый этап сознательно не включает процессы торговли и доставки — см. [docs/01-overview/Scope.md](docs/01-overview/Scope.md).

## Архитектурные принципы

Полный список с определениями — [docs/00-overview/Architecture_Principles.md](docs/00-overview/Architecture_Principles.md). Все решения первого этапа должны им соответствовать.

## Термины

Единые определения терминов (Unified Catalog, Working Catalog, SellerProduct и т.д.) — [docs/00-overview/Glossary.md](docs/00-overview/Glossary.md). Остальные документы используют термины без повторного описания.

## Структура репозитория

```
.
├── README.md                          — этот документ
├── docs/
│   ├── 00-overview/
│   │   ├── Glossary.md                 — единые определения терминов
│   │   └── Architecture_Principles.md  — единый список архитектурных принципов
│   ├── 01-overview/
│   │   ├── Vision.md                  — миссия, гипотеза, роли
│   │   ├── Scope.md                   — что входит в Stage 1 / что нет (единственный источник для этого списка)
│   │   └── Roadmap.md                 — порядок реализации, контрольные точки M1–M6
│   ├── 02-domain/
│   │   ├── Domain_Model.md             — бизнес-сущности и их ответственность
│   │   ├── Catalog_Model.md            — единый каталог vs каталоги продавцов
│   │   ├── Publication_Model.md        — жизненный цикл публикации
│   │   ├── Catalog_Template.md         — формат шаблона рабочего каталога (часть модели данных)
│   │   └── templates/
│   │       └── catalog_template_v1.xlsx — нормативный артефакт шаблона (PR-008), см. Catalog_Template.md
│   ├── 03-database/
│   │   ├── Physical_Model.md           — физическая модель данных (MySQL)
│   │   ├── DDL_Specification.md        — нормативные правила SQL DDL
│   │   ├── Coding_Standard.md          — naming conventions, стандарты схемы
│   │   └── Database_Migrations.md      — состав миграций 001–006 + Seed Data
│   ├── 04-services/
│   │   ├── Publication_Service.md      — серверная логика публикации каталога
│   │   ├── REST_API.md                 — контракт API (ресурсы и методы)
│   │   └── Publication_Workflow.md          — алгоритм (workflow) выполнения публикации
│   ├── 05-ui/
│   │   ├── Buyer_MVP.md                — интерфейс покупателя
│   │   ├── Seller_MVP.md               — кабинет продавца
│   │   └── Admin_MVP.md                — административный интерфейс
│   ├── 06-development/
│   │   ├── Bootstrap.md                — минимальная инженерная инфраструктура
│   │   ├── Development_Guidelines.md   — обязательные правила разработки
│   │   └── adr/                        — Architecture Decision Records (пусто до первого отклонения от Stage 1)
│   └── reviews/
│       └── Fable5_Review_Resolution.md — результаты разбора независимых аудитов и принятые по ним решения
└── database/
    └── migrations/                     — исполняемые SQL-миграции 001–006
```

Исполняемые SQL-миграции находятся не в `docs/`, а в [`database/migrations/`](database/migrations/) — документация на них ссылается, но не хранит их (см. [docs/03-database/Database_Migrations.md](docs/03-database/Database_Migrations.md)).

## Последовательность реализации

1. Database
2. Migrations
3. Seed Data
4. Publication Service
5. REST API
6. Buyer MVP
7. Seller MVP
8. Admin MVP

Изменение порядка допускается только при наличии технического обоснования (см. [docs/01-overview/Roadmap.md](docs/01-overview/Roadmap.md)).

## Definition of Done (Stage 1)

- База данных развёрнута.
- Продавцы самостоятельно публикуют каталоги.
- Покупатели используют единый каталог.
- Система функционирует без ручного сопровождения разработчиков.
- Получена первая регулярная выручка.

## Статус документации

Версия 1.0 — финальная спецификация GreenMarket Stage 1 после двух раундов редакторской ревизии. После утверждения изменения выполняются только через ADR ([docs/06-development/adr/](docs/06-development/adr/README.md)). Основной источник изменений после начала разработки — результаты эксплуатации системы и подтверждённые бизнес-требования.

По итогам независимых аудитов документации принят [docs/reviews/Fable5_Review_Resolution.md](docs/reviews/Fable5_Review_Resolution.md) — решения (Accepted/Deferred) по каждому замечанию. Принятые решения ещё не внесены в нормативные документы; до внесения правок документация по соответствующим пунктам считается неполной.

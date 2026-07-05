# GreenMarket Bootstrap

**Version:** 1.0
**Status:** Normative

## Назначение

Настоящий документ определяет минимальную инженерную инфраструктуру GreenMarket Stage 1. Bootstrap является первой стадией реализации проекта и создаёт полностью готовую среду разработки. Bootstrap не содержит бизнес-логики.

## Цели Bootstrap

После завершения Bootstrap любой разработчик должен иметь возможность: клонировать репозиторий; развернуть проект одной командой; получить готовую базу данных; запустить Backend; запустить Frontend; начать разработку без дополнительной настройки окружения.

## Состав Bootstrap

Структура репозитория; Docker Compose; Backend; Frontend; MySQL; Redis; система миграций; Seed Data; базовая CI-конфигурация.

## Структура репозитория

```text
greenmarket/
├── backend/
├── frontend/
├── database/
│   ├── migrations/
│   └── seeders/
├── docs/
├── docker/
├── scripts/
└── docker-compose.yml
```

## Docker

Bootstrap должен запускаться одной командой:

```bash
docker compose up
```

Контейнеры: nginx, php-fpm, mysql, redis, mailpit. Дополнительно допускается Adminer или phpMyAdmin.

## Backend

Backend должен обеспечивать: успешную сборку; подключение к MySQL; выполнение миграций; выполнение Seed Data; запуск REST API.

## Frontend

Frontend должен: успешно собираться; запускаться локально; иметь подключение к Backend API; отображать стартовую страницу приложения.

## База данных

После запуска Bootstrap автоматически выполняются: создание схемы → миграции → Seed Data. После завершения база полностью готова к работе.

## Проверка работоспособности

Система должна предоставлять endpoint `GET /api/v1/health`, отвечающий `{"status": "ok"}`. Endpoint используется системой мониторинга и CI.

## CI

Минимальный конвейер: Composer Install → NPM Install → Migration → Seed → Backend Tests → Frontend Build. Все проверки должны выполняться автоматически.

## Развёртывание новой среды

```text
git clone → docker compose up → composer install → npm install →
migrate → seed → backend ready → frontend ready
```

После завершения последовательности разработчик получает полностью работоспособную локальную среду.

## Ограничения Bootstrap

Bootstrap не реализует: Publication Service; Buyer Web; Seller Cabinet; Admin Cabinet; бизнес-логику; FSM; импорт Excel. Все перечисленные компоненты реализуются на следующих этапах разработки.

## Definition of Done

Bootstrap считается завершённым, если новый разработчик способен менее чем за 15 минут: развернуть проект; выполнить миграции; заполнить БД тестовыми данными; открыть Backend; открыть Frontend; получить успешный ответ Health API — без ручного изменения конфигурации проекта.

## Связь с другими документами

Структура базы данных определяется документом [Physical_Model.md](../03-database/Physical_Model.md). Правила миграций определяются документом [Database_Migrations.md](../03-database/Database_Migrations.md). Порядок реализации проекта определяется документом [Roadmap.md](../01-overview/Roadmap.md).

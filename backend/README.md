# GreenMarket Backend

PR-001 — Bootstrap. Запускающийся FastAPI-каркас, без единой строки бизнес-логики.

## Запуск

```bash
cd backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

```
GET /health
{"status": "UP"}
```

## Тесты

```bash
uv run pytest
```

## Структура

```
backend/
├── app/
│   ├── api/v1/        — REST-контроллеры (пусто, PR-008)
│   ├── application/    — сценарии использования (пусто, PR-007)
│   ├── domain/         — доменная модель (пусто, PR-006/007)
│   ├── infrastructure/ — репозитории, доступ к БД (пусто, PR-003)
│   ├── core/           — конфигурация приложения
│   └── main.py
└── tests/
```

## Отклонения от исходной спецификации PR-001

- **Нет вложенной `backend/database/`.** Миграции и seed-данные уже существуют
  в `../database/migrations/` и `../database/seeders/` на уровне корня
  репозитория (see `docs/03-database/Database_Migrations.md`) — дублировать их
  здесь означало бы два источника истины для одной и той же схемы.
- **Нет `alembic` в зависимостях.** Договорённость по стеку (см.
  `kwork/timeline.md`, п.30) явно фиксирует Database First и независимость SQL
  от ORM — миграции пишутся вручную по `docs/03-database/DDL_Specification.md`,
  а не генерируются из SQLAlchemy-моделей. Добавление Alembic сейчас создало бы
  соблазн смешать эти два подхода. Если появится реальная причина использовать
  Alembic только как раннер (без autogenerate), это отдельное решение будущего PR.

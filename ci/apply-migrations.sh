#!/bin/bash
# Применение SQL-миграций из database/migrations к схемам GreenMarket.
#
# Учёт применённого ведётся в таблице SchemaMigration внутри самой схемы:
# применяется только то, чего в ней ещё нет. Повторный запуск ничего не делает.
#
#   ci/apply-migrations.sh              применить недостающие миграции
#   ci/apply-migrations.sh --baseline   пометить все текущие файлы применёнными,
#                                       НЕ выполняя их — разовая операция для
#                                       схемы, которую накатывали руками до
#                                       появления этого скрипта
#
# Параметры подключения берутся из backend/.env (те же, что у бэкенда), схемы —
# DB_NAME и, если задан, TEST_DB_NAME. Переопределяются переменными окружения:
# ENV_FILE, MIGRATIONS_DIR, MYSQL_BIN.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/backend/.env}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-$REPO_ROOT/database/migrations}"
MYSQL_BIN="${MYSQL_BIN:-mysql}"

BASELINE=false
case "${1:-}" in
  --baseline) BASELINE=true ;;
  "") ;;
  *) echo "usage: $(basename "$0") [--baseline]" >&2; exit 2 ;;
esac

[[ -f "$ENV_FILE" ]] || { echo "нет файла окружения: $ENV_FILE" >&2; exit 1; }
[[ -d "$MIGRATIONS_DIR" ]] || { echo "нет каталога миграций: $MIGRATIONS_DIR" >&2; exit 1; }

env_value() {
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}

DB_HOST="$(env_value DB_HOST)"
DB_PORT="$(env_value DB_PORT)"
DB_USER="$(env_value DB_USER)"
DB_NAME="$(env_value DB_NAME)"
TEST_DB_NAME="$(env_value TEST_DB_NAME)"
export MYSQL_PWD="$(env_value DB_PASSWORD)"

[[ -n "$DB_NAME" ]] || { echo "DB_NAME не задан в $ENV_FILE" >&2; exit 1; }

# SQL приходит на stdin, результат — без рамок и заголовков.
mysql_run() {
  "$MYSQL_BIN" --protocol=TCP -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" \
    -D "$1" --batch --raw --silent
}

migrate_schema() {
  local schema="$1"
  echo "--- схема $schema"

  mysql_run "$schema" <<'SQL'
CREATE TABLE IF NOT EXISTS SchemaMigration (
    version    VARCHAR(255) NOT NULL,
    applied_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (version)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;
SQL

  local applied
  applied="$(mysql_run "$schema" <<< 'SELECT version FROM SchemaMigration;')"

  if $BASELINE && [[ -n "$applied" ]]; then
    echo "  схема уже отмечена: baseline выполняется один раз" >&2
    return 1
  fi

  local processed=0 file version
  for file in "$MIGRATIONS_DIR"/*.sql; do
    version="$(basename "$file" .sql)"
    if grep -qxF "$version" <<< "$applied"; then
      continue
    fi
    if $BASELINE; then
      echo "  отмечаю  $version"
    else
      echo "  применяю $version"
      mysql_run "$schema" < "$file"
    fi
    mysql_run "$schema" <<< "INSERT INTO SchemaMigration (version) VALUES ('$version');"
    processed=$((processed + 1))
  done

  if [[ $processed -eq 0 ]]; then
    echo "  нечего применять"
  fi
}

migrate_schema "$DB_NAME"
if [[ -n "$TEST_DB_NAME" ]]; then
  migrate_schema "$TEST_DB_NAME"
fi

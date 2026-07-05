-- Источник: https://chatgpt.com/s/t_6a480be1d16c8191aa7bbe616dc16c06 (GM m1)
-- Финальный план миграций (см. ../architecture/03-database/Database_Migrations.md) — раздельные CREATE TABLE 001-006.

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 001_create_product_groups.sql
| Purpose   : Создание справочника товарных групп
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE ProductGroup
(
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    parent_id   BIGINT UNSIGNED NULL
        COMMENT 'Родительская группа. NULL означает корневую группу.',

    name        VARCHAR(100) NOT NULL
        COMMENT 'Наименование товарной группы',

    sort_order  INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Порядок отображения внутри родительской группы',

    is_active   BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Признак активности группы',

    created_at  DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at  DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    INDEX idx_ProductGroup_parent (parent_id),
    INDEX idx_ProductGroup_name (name),

    CONSTRAINT fk_ProductGroup_parent
        FOREIGN KEY (parent_id)
        REFERENCES ProductGroup(id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARACTER SET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Единый справочник товарных групп GreenMarket';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1. UNIQUE(name) сознательно НЕ используется — одинаковые названия
|    допускаются в разных ветвях дерева (Фрукты/Апельсин, Соки/Апельсин,
|    Эфирные масла/Апельсин).
| 2. parent_id допускает NULL только для корневых групп.
| 3. Проверка отсутствия циклов дерева средствами БД сознательно НЕ
|    реализуется — контроль выполняется Admin Service перед изменением
|    структуры дерева.
| 4. Минимальный набор индексов создаётся в данной миграции.
|    Дополнительные составные индексы добавляются отдельными миграциями
|    после анализа реальных запросов (EXPLAIN ANALYZE).
|--------------------------------------------------------------------------
*/

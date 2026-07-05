-- Источник: https://chatgpt.com/s/t_6a480c745b6c81919c05164fd0a1cd58 (GM m2)
-- ПРИМЕЧАНИЕ: см. заголовок 001_create_product_groups.sql в этой же папке.

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 002_create_products.sql
| Purpose   : Создание единого справочника товарных позиций
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE Product
(
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    product_group_id  BIGINT UNSIGNED NOT NULL
        COMMENT 'Товарная группа',

    name              VARCHAR(150) NOT NULL
        COMMENT 'Наименование товарной позиции',

    description       TEXT NULL
        COMMENT 'Описание товарной позиции',

    is_active         BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Признак активности товарной позиции',

    created_at        DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at        DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    INDEX idx_Product_group (product_group_id),
    INDEX idx_Product_name (name),

    CONSTRAINT fk_Product_group
        FOREIGN KEY (product_group_id)
        REFERENCES ProductGroup(id)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Единый справочник товарных позиций GreenMarket';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1. Product — единый эталонный каталог платформы, общий для всех продавцов.
| 2. UNIQUE(name) сознательно НЕ используется — одинаковые названия
|    допускаются в разных товарных группах (идентификация выполняется
|    комбинацией ProductGroup + Product).
| 3. Удаление Product будет запрещено после создания FK
|    fk_SellerProduct_product в 003_create_seller_products.sql.
| 4. Product — справочник платформы: создание/изменение/деактивация —
|    только администраторами системы, продавцы Product не меняют.
| 5. Application Rule: вместо физического удаления — is_active.
|    Соблюдение правила обеспечивает Admin Service.
| 6. Минимальный набор индексов создаётся данной миграцией; составные
|    индексы — отдельной миграцией после EXPLAIN ANALYZE.
|--------------------------------------------------------------------------
*/

-- Источник: https://chatgpt.com/s/t_6a480d36a6188191806c4e11263c2930 (GM m3)
-- ПРИМЕЧАНИЕ: см. заголовок 001_create_product_groups.sql в этой же папке.

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 005_create_seller_products.sql
| Purpose   : Создание рабочего каталога продавцов
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE SellerProduct
(
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Постоянный идентификатор товара продавца (SellerProductId)',

    seller_id           BIGINT UNSIGNED NOT NULL
        COMMENT 'Продавец',

    product_id          BIGINT UNSIGNED NULL
        COMMENT 'Эталонная товарная позиция. NULL означает необходимость модерации',

    seller_name         VARCHAR(200) NOT NULL
        COMMENT 'Наименование товара продавца',

    price               DECIMAL(12,2) NOT NULL DEFAULT 0.00
        COMMENT 'Цена',

    stock               DECIMAL(12,3) NOT NULL DEFAULT 0.000
        COMMENT 'Остаток',

    unit                VARCHAR(30) NOT NULL
        COMMENT 'Единица измерения',

    description         TEXT NULL
        COMMENT 'Описание товара продавца',

    is_published        BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Признак публикации товара',

    moderation_status   VARCHAR(30) NOT NULL DEFAULT 'WAIT_PRODUCT'
        COMMENT 'Статус модерации',

    moderator_id        INT NULL
        COMMENT 'Администратор, выполняющий модерацию (users.id_user в aristotel_taxi)',

    moderated_at        DATETIME NULL
        COMMENT 'Дата модерации (UTC)',

    moderation_comment  TEXT NULL
        COMMENT 'Комментарий администратора',

    created_at          DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at          DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    INDEX idx_SellerProduct_seller (seller_id),
    INDEX idx_SellerProduct_product (product_id),
    INDEX idx_SellerProduct_status (moderation_status),
    INDEX idx_SellerProduct_published (is_published),

    CONSTRAINT fk_SellerProduct_seller
        FOREIGN KEY (seller_id) REFERENCES Seller(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT fk_SellerProduct_product
        FOREIGN KEY (product_id) REFERENCES Product(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT fk_SellerProduct_moderator
        FOREIGN KEY (moderator_id) REFERENCES users(id_user)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT chk_SellerProduct_price CHECK (price >= 0),
    CONSTRAINT chk_SellerProduct_stock CHECK (stock >= 0),
    CONSTRAINT chk_SellerProduct_moderation_status CHECK
        (moderation_status IN ('WAIT_PRODUCT', 'IN_PROGRESS', 'RESOLVED'))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Рабочий каталог товаров продавцов';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1.  SellerProduct — основная рабочая таблица подсистемы каталога.
| 2.  id (SellerProductId) никогда не изменяется после создания записи —
|     используется Publication Service для синхронизации рабочего каталога.
| 3.  product_id = NULL означает, что товар ожидает классификации
|     администратором.
| 4.  Допустимые значения moderation_status: WAIT_PRODUCT, IN_PROGRESS,
|     RESOLVED — перечень должен соответствовать
|     chk_SellerProduct_moderation_status.
| 5.  Application Rule: публикация/снятие с публикации — через is_published.
|     Физическое удаление SellerProduct не используется.
| 6.  fk_SellerProduct_product завершает правило из 002_create_products.sql:
|     удаление Product невозможно, пока существуют связанные товары.
| 7.  moderator_id ссылается напрямую на users(id_user) платформенной БД
|     aristotel_taxi (отдельной таблицы User в GreenMarket нет), FK
|     fk_SellerProduct_moderator — ON DELETE RESTRICT (физическое удаление
|     пользователей не предусматривается, деактивация — на стороне платформы).
| 8.  Application Rule: при изменении продавцом product_id Publication
|     Service автоматически переводит запись в WAIT_PRODUCT (эта миграция
|     только предоставляет поля хранения, поведение не реализует).
| 9.  Publication Service обязан явно устанавливать moderation_status;
|     DEFAULT 'WAIT_PRODUCT' — только защита от NULL.
| 10. Все бизнес-правила модерации реализует Publication Service — эта
|     миграция определяет только структуру хранения.
| 11. Минимальный набор индексов создаётся данной миграцией; составные
|     индексы ((seller_id, is_published), (seller_id, product_id) и др.) —
|     отдельной миграцией после EXPLAIN ANALYZE.
|--------------------------------------------------------------------------
*/

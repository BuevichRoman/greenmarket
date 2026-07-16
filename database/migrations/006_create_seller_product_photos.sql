-- Источник: https://chatgpt.com/s/t_6a480dc9c4048191b75fe31414bc7782 (GM m4)
-- ПРИМЕЧАНИЕ: см. заголовок 001_create_product_groups.sql в этой же папке.

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 006_create_seller_product_photos.sql
| Purpose   : Связь товаров продавцов с фотографиями
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE SellerProductPhoto
(
    seller_product_id  BIGINT UNSIGNED NOT NULL
        COMMENT 'Товар продавца',

    photo_id            BIGINT UNSIGNED NOT NULL
        COMMENT 'Фотография',

    sort_order           INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Порядок отображения фотографии',

    PRIMARY KEY (seller_product_id, photo_id),

    INDEX idx_SellerProductPhoto_photo (photo_id),
    INDEX idx_SellerProductPhoto_sort (seller_product_id, sort_order),

    CONSTRAINT fk_SellerProductPhoto_product
        FOREIGN KEY (seller_product_id) REFERENCES SellerProduct(id)
        ON DELETE CASCADE ON UPDATE RESTRICT,

    CONSTRAINT fk_SellerProductPhoto_photo
        FOREIGN KEY (photo_id) REFERENCES Photo(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Связь товаров продавцов с фотографиями';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1. Таблица реализует связь "многие ко многим" между SellerProduct и Photo.
| 2. Одна фотография может использоваться несколькими товарами продавцов —
|    дублирование файлов изображений не выполняется.
| 3. sort_order определяет порядок отображения фотографий товара (первая —
|    минимальное значение). Application Rule: уникальность sort_order
|    внутри одного товара средствами БД сознательно не контролируется —
|    упрощает изменение порядка без временных конфликтов UNIQUE.
| 4. ON DELETE CASCADE — только для связи с SellerProduct. Application Rule:
|    в штатном режиме Publication Service не удаляет SellerProduct
|    физически; CASCADE предназначен для административных операций,
|    аварийного восстановления, очистки тестовых данных.
| 5. ON DELETE RESTRICT — для связи с Photo: фотография не может быть
|    удалена, пока используется хотя бы одним товаром. Очистка
|    неиспользуемых фото — отдельным сервисом обслуживания.
| 6. Составной первичный ключ исключает повторное прикрепление одной и той
|    же фотографии к одному товару.
| 7. Таблица не содержит собственных бизнес-данных — только связи между
|    сущностями платформы.
| 8. Минимальный набор индексов создаётся данной миграцией; составные —
|    отдельной миграцией после EXPLAIN ANALYZE.
|--------------------------------------------------------------------------
*/

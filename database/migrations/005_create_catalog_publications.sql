-- Источник: https://chatgpt.com/s/t_6a480e6286248191b92448d82f4b639b (GM m5)
-- ПРИМЕЧАНИЕ: см. заголовок 001_create_product_groups.sql в этой же папке.

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 005_create_catalog_publications.sql
| Purpose   : Журнал публикаций рабочих каталогов продавцов
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE CatalogPublication
(
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    seller_id        BIGINT UNSIGNED NOT NULL
        COMMENT 'Продавец',

    version          INT UNSIGNED NOT NULL
        COMMENT 'Версия опубликованного рабочего каталога',

    publication_key  CHAR(36) NOT NULL
        COMMENT 'PublicationKey, использованный при публикации',

    catalog_hash     CHAR(64) NOT NULL
        COMMENT 'SHA-256 опубликованного рабочего каталога',

    published_at     DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата публикации (UTC)',

    published_by     BIGINT UNSIGNED NOT NULL
        COMMENT 'Пользователь, выполнивший публикацию',

    PRIMARY KEY (id),

    UNIQUE INDEX uk_CatalogPublication_key (publication_key),
    UNIQUE INDEX uk_CatalogPublication_version (seller_id, version),

    INDEX idx_CatalogPublication_seller (seller_id),
    INDEX idx_CatalogPublication_published_at (published_at),

    CONSTRAINT fk_CatalogPublication_seller
        FOREIGN KEY (seller_id) REFERENCES Seller(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT fk_CatalogPublication_user
        FOREIGN KEY (published_by) REFERENCES User(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Журнал публикаций рабочих каталогов GreenMarket';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1.  CatalogPublication — журнал событий: хранит только факты успешных
|     публикаций, содержимое рабочих каталогов не хранится.
| 2.  PublicationKey используется однократно — каждая успешная публикация
|     использует собственный уникальный ключ, повторное использование
|     невозможно.
| 3.  UNIQUE(seller_id, version) гарантирует невозможность повторной
|     публикации одной версии.
| 4.  Текущее состояние каталога НЕ определяется по журналу — оно хранится
|     в Seller (current_catalog_version/current_publication_key/
|     current_catalog_hash). CatalogPublication используется только для
|     аудита.
| 5.  Publication Service выполняет атомарную транзакцию PUBLISHING:
|     одновременно обновляются Seller, SellerProduct, SellerProductPhoto,
|     создаётся запись CatalogPublication.
| 6.  Application Rule: PublicationKey становится недействительным сразу
|     после успешной публикации; новый ключ создаётся при генерации
|     следующего рабочего каталога.
| 7.  User — системная сущность платформы, FK fk_CatalogPublication_user —
|     ON DELETE RESTRICT (деактивация пользователей — через User Service).
| 8.  Application Rule: после создания запись журнала неизменяема —
|     Publication Service выполняет только INSERT (UPDATE/DELETE не
|     используются). Для защиты на уровне СУБД рекомендуется отдельный
|     пользователь БД с правом только INSERT (и SELECT для чтения).
| 9.  Минимальный набор индексов создаётся данной миграцией; составные —
|     отдельной миграцией после EXPLAIN ANALYZE.
| 10. CatalogPublication — append-only журнал платформы; неизменность
|     обеспечивается правилами Publication Service и политикой доступа
|     к БД, а не только схемой.
|--------------------------------------------------------------------------
*/

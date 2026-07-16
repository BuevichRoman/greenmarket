-- ПРИМЕЧАНИЕ: см. заголовок 001_create_product_groups.sql в этой же папке.
-- Добавлена задним числом при первом реальном деплое на aristotel_taxi (сервер 104.171.133.95):
-- 003-006 (исходная нумерация) ссылались на таблицу Seller, которой не существовало ни в одной
-- среде — миграция рассчитана на пустую БД, но сама таблица Seller нигде не создавалась.
-- Владелец Seller — Platform (см. docs/03-database/Coding_Standard.md, раздел "Владение данными").

/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Migration : 003_create_seller.sql
| Purpose   : Создание учётной записи продавца (техническая сущность платформы)
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
*/

CREATE TABLE Seller
(
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    user_id     INT NOT NULL
        COMMENT 'Продавец в системе идентификации платформы (aristotel_taxi.users.id_user, роль Водитель)',

    is_active   BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Признак активности учётной записи продавца',

    created_at  DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at  DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    UNIQUE INDEX uk_Seller_user (user_id),

    CONSTRAINT fk_Seller_user
        FOREIGN KEY (user_id) REFERENCES users(id_user)
        ON DELETE RESTRICT ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Учётная запись продавца платформы (техническая сущность GreenMarket)';

/*
|--------------------------------------------------------------------------
| Архитектурные решения
|--------------------------------------------------------------------------
| 1. Seller — техническая учётная запись продавца, отдельная от Seller
|    Profile (публичная доменная модель, см. docs/02-domain/Seller_Profile.md,
|    PR-009) и от users платформенной БД aristotel_taxi.
| 2. user_id — прямая ссылка на существующего пользователя платформы
|    (aristotel_taxi.users.id_user) с ролью Водитель (id_role = 2). Отдельная
|    регистрация продавцов вне платформенной идентификации не производится.
| 3. UNIQUE(user_id) — один пользователь платформы не может иметь более
|    одной учётной записи продавца.
| 4. Тип user_id (INT, не BIGINT UNSIGNED) сознательно соответствует типу
|    users.id_user в aristotel_taxi — иначе FK fk_Seller_user не создастся.
| 5. current_catalog_version/current_publication_key/current_catalog_hash
|    сознательно не входят в эту миграцию — добавляются 008_alter_seller_catalog.sql
|    после создания CatalogPublication (007), которая на них ссылается по смыслу.
| 6. is_active — физическое удаление Seller не используется, деактивация —
|    через это поле.
|--------------------------------------------------------------------------
*/

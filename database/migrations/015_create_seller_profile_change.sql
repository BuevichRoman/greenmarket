-- Migration : 015_create_seller_profile_change.sql
-- Purpose   : Журнал изменений профиля продавца. Значения профиля лежат в
--             платформенном механизме свойств (users_prop_items_varchar|text),
--             но там физически нет ни автора, ни времени изменения — только
--             (id_users_prop, id_user, value). Валентин 06.08.2026 потребовал
--             «видеть, кто изменил», и лента этих записей в Admin Cabinet
--             принята им же вместо настоящих уведомлений (почта/мессенджер):
--             механизма уведомлений в системе не существует.
-- Note      : author_user_id — платформенный users.id_user, одинаково пригоден
--             и для продавца, и для администратора (Administrator.user_id тоже
--             ссылается на users). author_role различает их, потому что по
--             одному user_id этого не видно: админ технически тоже пользователь
--             платформы.
-- Note      : old_value/new_value NULL означает «значения не было» — в
--             users_prop_items_* колонка value объявлена NOT NULL, поэтому
--             пустое поле там представлено отсутствием строки, а не NULL.
-- Note      : author_role хранится строкой с CHECK, а не ENUM — по требованию
--             docs/03-database/Coding_Standard.md, раздел «Статусы»:
--             расширение перечня не должно требовать изменения структуры БД.
-- DBMS      : MySQL Community Server 8.0.16+

CREATE TABLE SellerProfileChange
(
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    seller_id      BIGINT UNSIGNED NOT NULL
        COMMENT 'Продавец, чей профиль изменён (Seller.id)',

    field          VARCHAR(64) NOT NULL
        COMMENT 'Имя поля профиля в терминах API GreenMarket (row, place, working_hours, short_description, phone, whatsapp), а не var платформенного свойства',

    old_value      TEXT NULL
        COMMENT 'Значение до изменения; NULL — поле не было заполнено',

    new_value      TEXT NULL
        COMMENT 'Значение после изменения; NULL — поле очищено',

    author_user_id INT NOT NULL
        COMMENT 'Автор изменения в системе идентификации платформы (aristotel_taxi.users.id_user)',

    author_role    VARCHAR(16) NOT NULL
        COMMENT 'В какой роли автор внёс изменение: сам продавец из книги или администратор через Admin API',

    created_at     DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Когда изменение внесено (UTC)',

    PRIMARY KEY (id),

    -- Отдельного индекса под ленту нет намеренно. Оба запроса журнала
    -- (глобальная лента и история одного продавца) сортируют по id, а не по
    -- created_at: несколько полей, изменённых одним запросом, получают
    -- одинаковую метку времени с точностью до секунды, и порядок внутри такой
    -- пачки был бы неопределённым. Глобальную ленту обслуживает PRIMARY KEY,
    -- а внутри idx_SellerProfileChange_seller InnoDB и так дописывает id, так
    -- что ORDER BY id DESC внутри продавца тоже покрыт. Индекс по created_at
    -- при этих запросах остался бы мёртвым.
    INDEX idx_SellerProfileChange_seller (seller_id),

    CONSTRAINT fk_SellerProfileChange_seller
        FOREIGN KEY (seller_id) REFERENCES Seller(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT fk_SellerProfileChange_author
        FOREIGN KEY (author_user_id) REFERENCES users(id_user)
        ON DELETE RESTRICT ON UPDATE RESTRICT,

    CONSTRAINT chk_SellerProfileChange_author_role CHECK
        (author_role IN ('SELLER', 'ADMIN'))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Журнал изменений полей профиля продавца';

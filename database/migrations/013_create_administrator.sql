-- Migration : 013_create_administrator.sql
-- Purpose   : Аутентификация администратора GreenMarket. До этой миграции
--             админских учётных данных не существовало вообще: единственная
--             админская операция (scripts/issue_activation_code.py) защищалась
--             только тем, что запускается по SSH на сервере. Admin API
--             (docs/04-services/REST_API.md) без этого не может ответить на
--             вопрос «кто вызывает».
-- Решение   : тот же механизм, что у продавца (одноразовый activation_code →
--             постоянный access_token, миграция 011), но своя таблица.
--             Платформенная роль (users.id_role = 4 «Администратор») намеренно
--             НЕ проверяется: иначе выдача админских прав превращалась бы в
--             изменение роли на стороне такси — внешняя зависимость, которой
--             решили избежать. Периметр admin-доступа равен периметру доступа
--             к серверу: код активации выдаёт тот, у кого есть SSH.
-- Note      : user_id обязателен и ссылается на users(id_user) не ради
--             авторизации, а потому что SellerProduct.moderator_id — FK на
--             users(id_user) (миграция 005): без платформенного пользователя
--             модерация не смогла бы записать, кто её выполнил.
-- DBMS      : MySQL Community Server 8.0.16+

CREATE TABLE Administrator
(
    id                         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    user_id                    INT NOT NULL
        COMMENT 'Администратор в системе идентификации платформы (aristotel_taxi.users.id_user)',

    is_active                  BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Признак активности учётной записи администратора (отзыв доступа без удаления записи)',

    access_token               VARCHAR(64) NULL
        COMMENT 'Постоянный рабочий токен администратора',

    activation_code            VARCHAR(32) NULL
        COMMENT 'Одноразовый код первичной активации, NULL после использования',

    activation_code_expires_at DATETIME NULL
        COMMENT 'TTL кода активации',

    activated_at               DATETIME NULL
        COMMENT 'Когда код активации был использован',

    created_at                 DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at                 DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    UNIQUE INDEX uk_Administrator_user (user_id),
    UNIQUE INDEX uk_Administrator_access_token (access_token),
    UNIQUE INDEX uk_Administrator_activation_code (activation_code),

    CONSTRAINT fk_Administrator_user
        FOREIGN KEY (user_id) REFERENCES users(id_user)
        ON DELETE RESTRICT ON UPDATE RESTRICT
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Учётная запись администратора GreenMarket';

-- ВНИМАНИЕ: это НЕ часть database/migrations/001-008.
-- Локальный/CI-стаб реальной платформенной таблицы aristotel_taxi.users —
-- нужен только для запуска тестов и dev-окружения. Минимальный набор полей:
-- только id_user, единственная колонка, реально используемая через FK в
-- GreenMarket-миграциях (003_create_seller.sql, 005_create_seller_products.sql,
-- 007_create_catalog_publications.sql — user_id/moderator_id/published_by).
-- На проде эта таблица не создаётся — она уже существует на платформе
-- (aristotel_taxi.users, роль Водитель переиспользуется как продавец).
--
-- До 1b089bf (16.07.2026) здесь стабились Seller/User/Photo как платформенные
-- таблицы — это устарело: Seller и Photo теперь собственные таблицы
-- GreenMarket (создаются миграциями 003/004), а отдельной таблицы User не
-- существует ни на платформе, ни в GreenMarket — ссылки идут на users.id_user
-- напрямую.
--
-- С 06.08.2026 файл стабит ещё и платформенный механизм расширяемых свойств
-- пользователя: колонки users.phone/users.wa и таблицы users_prop/
-- users_prop_items_varchar/users_prop_items_text (см. блок ниже). Их схема
-- снята с боевой aristotel_taxi — не «улучшать» её по вкусу: любое расхождение
-- со схемой прода (лишняя/недостающая колонка, другой тип, другой constraint)
-- это будущий баг, который тесты на локальном стабе не поймают.

CREATE DATABASE IF NOT EXISTS greenmarket
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE greenmarket;

CREATE TABLE users
(
    id_user INT NOT NULL AUTO_INCREMENT,
    name    VARCHAR(200) NOT NULL,
    PRIMARY KEY (id_user)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной таблицы aristotel_taxi.users — только для тестов/dev';

-- Колонки users, которые GreenMarket читает (никогда не пишет):
-- phone — читаем: предзаполнение витринного телефона в профиле продавца; BIGINT, как на платформе.
-- wa    — не читаем и не пишем: на боевой платформе не заполнена ни у одного пользователя,
--         предзаполнения WhatsApp в коде нет и не планируется. Объявлена только для того,
--         чтобы стаб не расходился с боевой схемой users.
ALTER TABLE users
    ADD COLUMN phone BIGINT NULL
        COMMENT 'СТАБ: учётный телефон платформы, только для чтения',
    ADD COLUMN wa VARCHAR(255) NULL
        COMMENT 'СТАБ: учётный WhatsApp платформы, только для чтения';

-- СТАБ платформенного механизма расширяемых свойств пользователя.
-- Боевые таблицы живут в aristotel_taxi и созданы платформой; здесь только то,
-- что читает и пишет GreenMarket. FK на field_type/users_roles намеренно нет —
-- этих словарей у нас локально не существует, а код к ним не обращается.
-- На проде в users_prop есть ещё name_ar/name_fr/name_es (UNIQUE, как name_ru/
-- name_en) и пять description_* TEXT NOT NULL — они здесь не стабятся по той
-- же причине: GreenMarket их не читает и не пишет.
CREATE TABLE users_prop
(
    id_users_prop  INT NOT NULL AUTO_INCREMENT,
    var            VARCHAR(150) NOT NULL,
    name_ru        VARCHAR(255) NULL,
    name_en        VARCHAR(255) NULL,
    active         TINYINT(1) NOT NULL DEFAULT 1,
    value_type     INT NOT NULL DEFAULT 1,
    `some`         TINYINT(1) NOT NULL DEFAULT 0,
    visibility     TINYINT(1) NOT NULL DEFAULT 12,
    PRIMARY KEY (id_users_prop),
    UNIQUE INDEX uk_users_prop_var (var),
    UNIQUE INDEX uk_users_prop_name_ru (name_ru),
    UNIQUE INDEX uk_users_prop_name_en (name_en)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop — только для тестов/dev';

CREATE TABLE users_prop_items_varchar
(
    id_users_prop INT NOT NULL,
    id_user       INT NOT NULL,
    value         VARCHAR(255) NOT NULL,
    PRIMARY KEY (id_user, id_users_prop)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop_items_varchar — только для тестов/dev';

CREATE TABLE users_prop_items_text
(
    id_users_prop INT NOT NULL,
    id_user       INT NOT NULL,
    value         TEXT NOT NULL,
    PRIMARY KEY (id_user, id_users_prop)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной users_prop_items_text — только для тестов/dev';

-- Определения свойств GreenMarket. На проде заведены вручную 06.08.2026
-- (users_prop — конфигурационная таблица платформы, не наша миграция).
-- Здесь повторены, чтобы локальная база вела себя как боевая.
-- value_type: 1 = varchar, 2 = text. visibility 15 = виден всем, включая
-- неавторизованного покупателя (см. COLUMN_COMMENT боевой users_prop.visibility).
INSERT INTO users_prop (var, name_ru, name_en, value_type, visibility) VALUES
    ('gm_seller_row',               'GreenMarket: ряд на рынке',              'GreenMarket: market row',        1, 15),
    ('gm_seller_place',             'GreenMarket: место на рынке',            'GreenMarket: market place',      1, 15),
    ('gm_seller_working_hours',     'GreenMarket: часы работы',               'GreenMarket: working hours',     1, 15),
    ('gm_seller_short_description', 'GreenMarket: краткое описание продавца', 'GreenMarket: short description', 2, 15),
    ('gm_seller_phone',             'GreenMarket: телефон продавца',          'GreenMarket: seller phone',      1, 15),
    ('gm_seller_whatsapp',          'GreenMarket: WhatsApp продавца',         'GreenMarket: seller WhatsApp',   1, 15),
    -- Заведено 10.08.2026 вместе со справочником рынков (миграция 017). Хранит
    -- Market.id строкой: users_prop умеет varchar и text, а внешнего ключа
    -- отсюда в таблицу GreenMarket быть не может — существование рынка
    -- проверяет SellerProfileService.
    ('gm_seller_market_id',         'GreenMarket: рынок продавца',            'GreenMarket: seller market',     1, 15);

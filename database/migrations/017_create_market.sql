-- Migration : 017_create_market.sql
-- Purpose   : Рынок как отдельная сущность. Валентин 09.08.2026 спросил, где
--             гео-координаты магазина — их не было нигде: у продавца есть ряд и
--             место (координаты внутри рынка), но сам рынок в системе не
--             существовал. Экран «Карта» в Customer UI рисовать было нечем.
-- Note      : Сущность отделена от профиля продавца по Seller_Profile.md, §3:
--             название, адрес и координаты принадлежат рынку, а не каждому из
--             сотен его продавцов. Ряд и место остаются в профиле продавца —
--             это его координаты внутри рынка.
-- Note      : latitude/longitude — DECIMAL, а не DOUBLE: координаты сравниваются
--             и показываются как есть, двоичная погрешность здесь ни к чему.
--             DECIMAL(10,7) хватает на любую точку Земли с точностью ~1 см.
-- Note      : Координаты NULL допустимы — рынок можно завести по названию и
--             адресу до того, как кто-то снял точку. Такой рынок в карточке
--             продавца отдаётся без координат, а не прячется.
-- Note      : Связь с продавцом хранится не здесь, а профильным свойством
--             `gm_seller_market_id` в платформенном users_prop, как и остальной
--             профиль (см. Seller_Profile.md, §10). Внешнего ключа оттуда сюда
--             нет и быть не может: users_prop — таблица платформы, GreenMarket
--             ею не владеет. Существование рынка проверяет SellerProfileService.
-- DBMS      : MySQL Community Server 8.0.16+

CREATE TABLE Market
(
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT
        COMMENT 'Первичный ключ',

    name       VARCHAR(200) NOT NULL
        COMMENT 'Название рынка, как его знает покупатель',

    address    VARCHAR(500) NOT NULL
        COMMENT 'Почтовый адрес рынка',

    latitude   DECIMAL(10,7) NULL
        COMMENT 'Широта точки рынка; NULL — координата ещё не снята',

    longitude  DECIMAL(10,7) NULL
        COMMENT 'Долгота точки рынка; NULL — координата ещё не снята',

    is_active  BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Рынок доступен для выбора продавцом и показывается покупателю',

    created_at DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id)
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Рынок, на котором торгуют продавцы GreenMarket';

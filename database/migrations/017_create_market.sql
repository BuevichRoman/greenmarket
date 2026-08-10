-- Migration : 017_create_market.sql
-- Purpose   : Место торговли как отдельная сущность. Валентин 09.08.2026
--             спросил, где гео-координаты магазина — их не было нигде: у
--             продавца есть ряд и место (координаты внутри рынка), но самого
--             места торговли в системе не существовало. Экран «Карта» в
--             Customer UI рисовать было нечем.
-- Note      : Сущность отделена от профиля продавца по Seller_Profile.md, §3:
--             название, адрес и координаты принадлежат месту торговли, а не
--             каждому из сотен его продавцов. Ряд и место остаются в профиле
--             продавца — это его координаты внутри рынка.
-- Note      : Таблица хранит два типа точек (`type`, требование Валентина от
--             10.08.2026): рынок с множеством продавцов и отдельно стоящую
--             лавку в городе или деревне. Второй таблицы под лавку нет
--             намеренно — набор полей и способ показа на карте у них
--             одинаковые, различается только смысл: у лавки один продавец и
--             нет ряда с местом. Имя Market сохранено, потому что на него
--             ссылается уже согласованная нормативка (Seller_Profile.md, §3).
-- Note      : latitude/longitude — DECIMAL, а не DOUBLE: координаты сравниваются
--             и показываются как есть, двоичная погрешность здесь ни к чему.
--             DECIMAL(10,7) хватает на любую точку Земли с точностью ~1 см.
-- Note      : Координаты NULL допустимы — точку можно завести по названию и
--             адресу до того, как кто-то снял координаты. Такая точка в карточке
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
        COMMENT 'Название места торговли, как его знает покупатель',

    type       VARCHAR(16) NOT NULL DEFAULT 'MARKET'
        COMMENT 'Тип точки: MARKET — рынок с рядами и множеством продавцов, SHOP — отдельно стоящая лавка',

    address    VARCHAR(500) NOT NULL
        COMMENT 'Почтовый адрес места торговли',

    latitude   DECIMAL(10,7) NULL
        COMMENT 'Широта точки; NULL — координата ещё не снята',

    longitude  DECIMAL(10,7) NULL
        COMMENT 'Долгота точки; NULL — координата ещё не снята',

    is_active  BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Точка доступна для выбора продавцом и показывается покупателю',

    created_at DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        COMMENT 'Дата создания записи (UTC)',

    updated_at DATETIME NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
        COMMENT 'Дата последнего изменения записи (UTC)',

    PRIMARY KEY (id),

    -- Строкой с CHECK, а не ENUM — по docs/03-database/Coding_Standard.md,
    -- раздел «Статусы»: расширение перечня (ярмарка, павильон, ...) не должно
    -- требовать изменения структуры таблицы.
    CONSTRAINT chk_Market_type CHECK (type IN ('MARKET', 'SHOP'))
)
ENGINE = InnoDB
DEFAULT CHARSET = utf8mb4
COLLATE = utf8mb4_0900_ai_ci
COMMENT = 'Место торговли GreenMarket: рынок или отдельно стоящая лавка';

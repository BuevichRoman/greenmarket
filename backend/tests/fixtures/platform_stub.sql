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

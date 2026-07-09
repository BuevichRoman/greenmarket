-- ВНИМАНИЕ: это НЕ часть database/migrations/001-006.
-- Локальный/CI-стаб платформенных таблиц Seller/User/Photo (iBronevik) — нужен
-- только для запуска тестов и dev-окружения, пока нет доступа к реальному
-- окружению iBronevik. Состав полей — минимальный, только то, что реально
-- используется через FK в GreenMarket-миграциях (см.
-- docs/03-database/Physical_Model.md). На проде эти таблицы не создаются —
-- они уже существуют на платформе.

CREATE DATABASE IF NOT EXISTS greenmarket
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE greenmarket;

CREATE TABLE Seller
(
    id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(200)    NOT NULL,
    PRIMARY KEY (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной таблицы iBronevik — только для тестов/dev';

CREATE TABLE User
(
    id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(200)    NOT NULL,
    PRIMARY KEY (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной таблицы iBronevik — только для тестов/dev';

CREATE TABLE Photo
(
    id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    url VARCHAR(500)    NOT NULL,
    PRIMARY KEY (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'СТАБ платформенной таблицы iBronevik — только для тестов/dev';

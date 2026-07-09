/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Seeder    : 001_product_groups.sql
| Purpose   : Начальное наполнение дерева товарных групп (ProductGroup)
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
| Соответствует разделу "Seed Data" в
| docs/03-database/Database_Migrations.md (минимальное дерево категорий).
|
| Область: только Admin-owned справочные данные GreenMarket (ProductGroup).
| Товары — в 002_products.sql (зависит от этого файла: подгруппы уже должны
| существовать).
|
| Данные предназначены для разработки/тестирования/демонстрации, не для
| production-каталога, который наполняется администраторами и продавцами.
|
| Запускать после применения миграций 001-006, строго на пустой БД, до
| 002_products.sql. Все id — через AUTO_INCREMENT, фиксированные значения
| не используются.
|
| Seeder является минимальным нормативным каталогом Stage 1 — не расширять
| до полного ассортимента рынка вручную здесь; реальный каталог растёт через
| административную модерацию (см. docs/03-database/Database_Migrations.md).
|--------------------------------------------------------------------------
*/

-- Кодировка соединения: без этого кириллица заливается как mojibake, если
-- клиент по умолчанию использует не utf8mb4.
SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- ProductGroup: корневые товарные группы
-- --------------------------------------------------------------------------
INSERT INTO ProductGroup (name, sort_order) VALUES
    ('Фрукты', 1),
    ('Овощи', 2),
    ('Молочные продукты', 3),
    ('Мясо', 4),
    ('Рыба', 5),
    ('Напитки', 6);

-- --------------------------------------------------------------------------
-- ProductGroup: подгруппы (parent_id определяется по имени корневой группы)
-- --------------------------------------------------------------------------
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Цитрусовые', 1 FROM ProductGroup WHERE name = 'Фрукты';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Яблоки', 2 FROM ProductGroup WHERE name = 'Фрукты';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Бананы', 3 FROM ProductGroup WHERE name = 'Фрукты';

INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Томаты', 1 FROM ProductGroup WHERE name = 'Овощи';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Огурцы', 2 FROM ProductGroup WHERE name = 'Овощи';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Картофель', 3 FROM ProductGroup WHERE name = 'Овощи';

INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Молоко', 1 FROM ProductGroup WHERE name = 'Молочные продукты';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Сыр', 2 FROM ProductGroup WHERE name = 'Молочные продукты';
INSERT INTO ProductGroup (parent_id, name, sort_order)
SELECT id, 'Йогурты', 3 FROM ProductGroup WHERE name = 'Молочные продукты';

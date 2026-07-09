/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Seeder    : 002_products.sql
| Purpose   : Начальное наполнение единого справочника товаров (Product)
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
| Соответствует разделу "Seed Data" в
| docs/03-database/Database_Migrations.md (минимальный каталог товаров).
|
| Область: только Admin-owned справочные данные GreenMarket (Product).
| Зависит от 001_product_groups.sql — запускать строго после него.
|
| Данные предназначены для разработки/тестирования/демонстрации, не для
| production-каталога, который наполняется администраторами и продавцами.
|
| Все id — через AUTO_INCREMENT, фиксированные значения не используются.
|--------------------------------------------------------------------------
*/

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- Product: минимальный каталог товаров.
-- Привязка — к конечной (листовой) категории, если для корневой группы уже
-- созданы подгруппы в 001_product_groups.sql; товар не должен ссылаться на
-- группу, у которой есть дочерние подгруппы. Если подгруппы для товара нет
-- (Лук, Мясо, Рыба, Напитки) — товар остаётся на корневой группе, это тоже
-- валидный лист.
-- --------------------------------------------------------------------------
INSERT INTO Product (product_group_id, name)
SELECT id, 'Апельсин' FROM ProductGroup WHERE name = 'Цитрусовые';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Лимон' FROM ProductGroup WHERE name = 'Цитрусовые';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Банан' FROM ProductGroup WHERE name = 'Бананы';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Яблоко' FROM ProductGroup WHERE name = 'Яблоки';

INSERT INTO Product (product_group_id, name)
SELECT id, 'Помидор' FROM ProductGroup WHERE name = 'Томаты';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Огурец' FROM ProductGroup WHERE name = 'Огурцы';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Картофель' FROM ProductGroup WHERE name = 'Картофель';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Лук' FROM ProductGroup WHERE name = 'Овощи';

INSERT INTO Product (product_group_id, name)
SELECT id, 'Молоко' FROM ProductGroup WHERE name = 'Молоко';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Сыр' FROM ProductGroup WHERE name = 'Сыр';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Йогурт' FROM ProductGroup WHERE name = 'Йогурты';

INSERT INTO Product (product_group_id, name)
SELECT id, 'Говядина' FROM ProductGroup WHERE name = 'Мясо';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Курица' FROM ProductGroup WHERE name = 'Мясо';

INSERT INTO Product (product_group_id, name)
SELECT id, 'Сардина' FROM ProductGroup WHERE name = 'Рыба';
INSERT INTO Product (product_group_id, name)
SELECT id, 'Тунец' FROM ProductGroup WHERE name = 'Рыба';

INSERT INTO Product (product_group_id, name)
SELECT id, 'Минеральная вода' FROM ProductGroup WHERE name = 'Напитки';

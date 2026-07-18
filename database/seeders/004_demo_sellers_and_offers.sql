/*
|--------------------------------------------------------------------------
| GreenMarket
|--------------------------------------------------------------------------
| Seeder    : 004_demo_sellers_and_offers.sql
| Purpose   : Демо-продавцы и опубликованные предложения (Seller/SellerProduct)
| DBMS      : MySQL Community Server 8.0.16+
|--------------------------------------------------------------------------
| Наполняет рабочий каталог продавцов демонстрационными данными для Buyer
| Web (Catalog API, docs/04-services/REST_API.md) — до этого сидера
| `SellerProduct` пуст на любом стенде, и `/api/v1/catalog/*` возвращает
| только пустой каталог (product_count: 0 везде).
|
| Зависит от `id_user` трёх продавцов в `users` (`Демо: Ферма Ромашково`,
| `Демо: Хутор Заречный`, `Демо: Сад Плодовый`) и от 001/002 (ProductGroup/
| Product). Локально/в CI эти пользователи заводятся 003_demo_platform_users.sql.
| На реальном окружении (aristotel_taxi) 003 не запускается (см. его
| заголовок) — вместо этого нужно заранее вставить в реальную `users` три
| строки с ТАКИМИ ЖЕ значениями `name`, что и в 003 (например, платформа
| выделяет для этого реальные тестовые/демо-аккаунты с ролью Водитель и
| переименовывает их) — этот файл сам ищет продавцов по `name`, от способа
| получения `user_id` не зависит.
|
| Специально для лёгкой идентификации/последующей очистки: seller_name
| каждого предложения начинается с "Демо: " — вся демо-часть каталога
| удаляется одним DELETE FROM SellerProduct WHERE seller_name LIKE 'Демо:%'
| (плюс сами Seller/users, если нужно полностью откатить демо-данные).
|
| Три продавца намеренно продают частично одинаковые товары по разной (и
| местами одинаковой) цене — демонстрирует сравнение предложений на
| карточке товара (docs/05-ui/Customer_UI_UX.md) и детерминированный
| tie-break при равной цене (см. CatalogUseCase._visible_offers_by_product).
|--------------------------------------------------------------------------
*/

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- Seller: демо-продавцы
-- --------------------------------------------------------------------------
INSERT INTO Seller (user_id, is_active)
SELECT id_user, TRUE FROM users WHERE name = 'Демо: Ферма Ромашково';
INSERT INTO Seller (user_id, is_active)
SELECT id_user, TRUE FROM users WHERE name = 'Демо: Хутор Заречный';
INSERT INTO Seller (user_id, is_active)
SELECT id_user, TRUE FROM users WHERE name = 'Демо: Сад Плодовый';

-- --------------------------------------------------------------------------
-- SellerProduct: предложения продавца «Демо: Ферма Ромашково»
-- --------------------------------------------------------------------------
INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Яблоко', 89.90, 120.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Ферма Ромашково' AND p.name = 'Яблоко';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Огурец', 120.00, 45.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Ферма Ромашково' AND p.name = 'Огурец';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Картофель', 35.50, 300.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Ферма Ромашково' AND p.name = 'Картофель';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Молоко', 79.00, 60.000, 'л', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Ферма Ромашково' AND p.name = 'Молоко';

-- --------------------------------------------------------------------------
-- SellerProduct: предложения продавца «Демо: Хутор Заречный»
-- --------------------------------------------------------------------------
INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Яблоко', 94.00, 80.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Хутор Заречный' AND p.name = 'Яблоко';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Огурец', 115.00, 30.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Хутор Заречный' AND p.name = 'Огурец';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Курица', 210.00, 25.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Хутор Заречный' AND p.name = 'Курица';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Сыр', 450.00, 15.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Хутор Заречный' AND p.name = 'Сыр';

-- --------------------------------------------------------------------------
-- SellerProduct: предложения продавца «Демо: Сад Плодовый»
-- --------------------------------------------------------------------------
INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Яблоко', 89.90, 50.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Сад Плодовый' AND p.name = 'Яблоко';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Банан', 99.00, 70.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Сад Плодовый' AND p.name = 'Банан';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Апельсин', 110.00, 40.000, 'кг', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Сад Плодовый' AND p.name = 'Апельсин';

INSERT INTO SellerProduct (seller_id, product_id, seller_name, price, stock, unit, description, is_published, moderation_status)
SELECT s.id, p.id, 'Демо: Минеральная вода', 45.00, 200.000, 'шт', 'Демо-предложение для проверки Catalog API.', TRUE, 'RESOLVED'
FROM Seller s JOIN users u ON u.id_user = s.user_id, Product p
WHERE u.name = 'Демо: Сад Плодовый' AND p.name = 'Минеральная вода';

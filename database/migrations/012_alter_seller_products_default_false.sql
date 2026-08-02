-- Migration : 012_alter_seller_products_default_false.sql
-- Purpose   : Safety by default. SellerProduct.is_published создавался с
--             DEFAULT TRUE — вставка, не указавшая видимость явно (руками через
--             phpMyAdmin, миграцией, будущим кодом), молча показывала товар
--             покупателю. Безопасный дефолт — обратный: неполная вставка
--             приводит к непубликуемому состоянию, а видимость назначается
--             только осознанно (Publication Service, модерация, Admin API).
-- Note      : Существующие строки не трогаются — DEFAULT влияет только на новые
--             вставки. Штатный путь публикации (Publication Service) всегда
--             передаёт is_published явно, поэтому поведение продукта не меняется.
-- DBMS      : MySQL Community Server 8.0.16+

ALTER TABLE SellerProduct
    ALTER COLUMN is_published SET DEFAULT FALSE;

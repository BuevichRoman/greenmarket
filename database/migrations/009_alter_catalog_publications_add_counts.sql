-- Migration : 009_alter_catalog_publications_add_counts.sql
-- Purpose   : created_count/updated_count/deactivated_count существовали только в
--             одноразовом PublicationResult (backend/app/publication/publication_result.py)
--             и никогда не сохранялись — без них Экран 5 Seller Cabinet
--             (docs/05-ui/Seller_MVP.md) не может показать историю публикаций.
-- DBMS      : MySQL Community Server 8.0.16+

ALTER TABLE CatalogPublication
    ADD COLUMN created_count     INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Создано SellerProduct при этой публикации',
    ADD COLUMN updated_count     INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Обновлено SellerProduct при этой публикации',
    ADD COLUMN deactivated_count INT UNSIGNED NOT NULL DEFAULT 0
        COMMENT 'Деактивировано SellerProduct при этой публикации';

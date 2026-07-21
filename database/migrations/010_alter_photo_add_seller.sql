-- Источник: docs/superpowers/specs/2026-07-21-photo-upload-backend-design.md
-- Трассируемость: какой продавец загрузил фото через POST /api/v1/photos.
-- Не enforced ownership check (нет FK на Seller — тот же паттерн, что
-- SellerProduct.seller_id/CatalogPublication.seller_id, см. SellerGateway).

ALTER TABLE Photo
    ADD COLUMN seller_id BIGINT UNSIGNED NULL
        COMMENT 'Продавец, загрузивший фото (трассируемость, не FK)',
    ADD INDEX idx_Photo_seller (seller_id);

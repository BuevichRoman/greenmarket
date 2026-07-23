-- Источник: docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md
-- Переносит access_token из SELLER_ACCESS_TOKENS (.env) в БД + добавляет
-- одноразовый activation_code для первичной привязки персональной копии
-- Google Sheets продавца к его Seller.

ALTER TABLE Seller
    ADD COLUMN access_token               VARCHAR(64)  NULL COMMENT 'Постоянный рабочий токен продавца (заменяет SELLER_ACCESS_TOKENS)',
    ADD COLUMN activation_code            VARCHAR(32)  NULL COMMENT 'Одноразовый код первичной привязки, NULL после использования',
    ADD COLUMN activation_code_expires_at DATETIME     NULL COMMENT 'TTL кода активации',
    ADD COLUMN spreadsheet_id             VARCHAR(100) NULL COMMENT 'ID персональной копии Google Sheets продавца (справочно)',
    ADD COLUMN activated_at               DATETIME     NULL COMMENT 'Когда код активации был использован',
    ADD UNIQUE INDEX uk_Seller_access_token (access_token),
    ADD UNIQUE INDEX uk_Seller_activation_code (activation_code);

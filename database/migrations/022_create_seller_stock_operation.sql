-- GM-VOICE-002: журнал идемпотентных операций продажи/поступления.
-- MySQL 8 / InnoDB. Остаток и операция записываются одной транзакцией.
CREATE TABLE SellerStockOperation (
    id BIGINT NOT NULL AUTO_INCREMENT,
    seller_id INT NOT NULL,
    seller_product_id INT NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    operation ENUM('SALE', 'INCOMING') NOT NULL,
    quantity DECIMAL(12,3) NOT NULL,
    unit VARCHAR(30) NOT NULL,
    stock_before DECIMAL(12,3) NOT NULL,
    stock_after DECIMAL(12,3) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_SellerStockOperation_seller_key UNIQUE (seller_id, idempotency_key),
    CONSTRAINT fk_SellerStockOperation_product
        FOREIGN KEY (seller_product_id) REFERENCES SellerProduct(id),
    CONSTRAINT chk_SellerStockOperation_quantity CHECK (quantity > 0),
    INDEX ix_SellerStockOperation_product_created (seller_product_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

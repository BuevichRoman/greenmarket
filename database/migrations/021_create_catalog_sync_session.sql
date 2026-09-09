-- Migration : 021_create_catalog_sync_session.sql
-- Purpose   : Постоянное хранение рабочей сессии сверки каталога и её
--             построчного снимка (ТЗ «Catalog Sync Session + per-item Baseline»).
--             Третья и последняя backend-зависимость двухсторонней синхронизации:
--             baseline обязан пережить перезагрузку браузера и параллельные
--             вкладки, поэтому в Appsmith его держать нельзя.
-- Note      : `session_id` — UUID отдельной колонкой, наружу отдаётся он, а не
--             первичный ключ. Последовательный id позволял бы перебирать чужие
--             сессии, а изоляция продавцов не должна держаться на одной
--             проверке в коде.
-- Note      : `baseline_created_at` вместо пятого статуса. «Сессия активна,
--             снимка ещё нет» и «активна, снимок есть» — это наличие отметки,
--             а не отдельное состояние. Она же служит замком: снимок создаётся
--             условным UPDATE этой колонки из NULL, и второй одновременный
--             запрос не затронет ни одной строки.
-- Note      : у снимка НЕТ внешнего ключа на SellerProduct. Baseline обязан
--             пережить удаление позиции — «существование позиции» является
--             частью трёхстороннего сравнения, а FK сделал бы снимок зависимым
--             от текущего каталога.
-- Note      : PK (session_id, seller_product_id) — суррогатный ключ строке
--             снимка не нужен, а составной сам запрещает две записи об одной
--             позиции в одном снимке.
-- Note      : ON DELETE CASCADE — при удалении сессии по сроку хранения (90
--             дней) её снимок уходит вместе с ней. Обычная очистка удаляет
--             снимок раньше, оставляя сессию следом.
-- DBMS      : MySQL Community Server 8.0.16+

CREATE TABLE CatalogSyncSession (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    session_id          CHAR(36)     NOT NULL,
    seller_id           INT          NOT NULL,
    status              VARCHAR(20)  NOT NULL,
    created_at          DATETIME     NOT NULL,
    expires_at          DATETIME     NOT NULL,
    baseline_created_at DATETIME     NULL,
    idempotency_key     VARCHAR(64)  NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_CatalogSyncSession_session_id UNIQUE (session_id),
    CONSTRAINT uk_CatalogSyncSession_idempotency UNIQUE (seller_id, idempotency_key),
    INDEX idx_CatalogSyncSession_seller_status (seller_id, status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE CatalogSyncBaseline (
    session_id        BIGINT        NOT NULL,
    seller_product_id INT           NOT NULL,
    seller_sku        VARCHAR(64)   NULL,
    product_id        INT           NULL,
    seller_name       VARCHAR(200)  NOT NULL,
    price             DECIMAL(12,2) NOT NULL,
    stock             DECIMAL(12,3) NOT NULL,
    unit              VARCHAR(30)   NOT NULL,
    description       TEXT          NULL,
    origin_country    VARCHAR(100)  NULL,
    supply_date       DATE          NULL,
    is_published      BOOLEAN       NOT NULL,
    version           INT           NOT NULL,
    PRIMARY KEY (session_id, seller_product_id),
    CONSTRAINT fk_CatalogSyncBaseline_session FOREIGN KEY (session_id)
        REFERENCES CatalogSyncSession (id) ON DELETE CASCADE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

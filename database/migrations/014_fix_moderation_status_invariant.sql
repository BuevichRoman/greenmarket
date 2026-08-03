-- Migration : 014_fix_moderation_status_invariant.sql
-- Purpose   : Привести существующие строки к инварианту
--             «WAIT_PRODUCT/IN_PROGRESS ⟺ product_id IS NULL».
--             Модерация Stage 1 — это классификация, то есть привязка
--             предложения к справочнику Product (docs/02-domain/Catalog_Model.md,
--             docs/05-ui/Admin_MVP.md). До этого приложение ставило
--             WAIT_PRODUCT всем новым строкам независимо от того, выбрал ли
--             продавец товарную позицию — статус существовал, но ничего не
--             значил и не участвовал ни в одном правиле.
-- Note      : IN_PROGRESS с пустым product_id — законное состояние (модератор
--             взял заявку в работу), поэтому такие строки не трогаются.
--             Отметки модератора (moderator_id/moderated_at/moderation_comment)
--             тоже не трогаются: миграция чинит статус, а не переписывает
--             историю чьих-то решений.
-- DBMS      : MySQL Community Server 8.0.16+

UPDATE SellerProduct
SET moderation_status = 'RESOLVED'
WHERE product_id IS NOT NULL
  AND moderation_status <> 'RESOLVED';

UPDATE SellerProduct
SET moderation_status = 'WAIT_PRODUCT'
WHERE product_id IS NULL
  AND moderation_status = 'RESOLVED';

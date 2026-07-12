# 0002. Переход от генерируемого Excel к статическому шаблону Google Sheets (CR-001)

**Дата:** 2026-07-12
**Статус:** Принято

## Контекст

При переходе Publication Pipeline на Google Sheets как единственный источник
публикации Stage 1 обнаружено архитектурное противоречие: модель `_System`
унаследована от сценария, где GreenMarket сам генерирует рабочий каталог
(Excel) и вписывает в него служебные данные конкретной публикации
(`PublicationKey`, `CatalogHash`). Google Sheets в Stage 1 — статический
шаблон, который продавец копирует себе сам («Создать копию шаблона» →
заполнить → расшарить на Service Account → опубликовать); GreenMarket
никогда не пишет в таблицу (ни автоматического создания, ни обратной
синхронизации). Следовательно, сервер не может заранее вписать в документ
значения, которые сам же должен потом сверить.

## Решение

1. **`PublicationKey`** становится внутренним идентификатором публикации
   GreenMarket: генерируется сервером на каждый вызов `POST /publications`
   (`uuid.uuid4()`), хранится только в `CatalogPublication` и
   `Seller.current_publication_key`. Документ Google Sheets о нём не знает.
2. **`CatalogHash`** вычисляется сервером (`HashCalculator`) из содержимого
   `RawWorkbook`, полученного `GoogleSheetsParser`, — до `Validator`, чтобы
   зависеть только от содержимого документа, а не от результата валидации.
   Документ `CatalogHash` тоже не содержит.
3. **Лист `_System`** перестаёт хранить данные конкретной публикации.
   Минимальный состав — `TemplateVersion`, `TemplateId` (метаданные шаблона).
   `StructureValidator` продолжает требовать лист, но проверяет только эти
   поля.
4. **`StructureValidator`/`Mapper`** перестают читать из `_System`
   `PublicationKey`/`CatalogHash` — этих полей там больше нет.
5. **`BusinessValidator._validate_publication_key`** удаляется целиком —
   сверять в документе больше нечего. Оставшаяся проверка (дубли
   `SellerProductId`) не требует ни `seller_id`, ни `SellerGateway`.
6. **`PublicationService.publish()`** получает `publication_key`/
   `catalog_hash` явными параметрами от вызывающего кода (новый
   `PublicationUseCase`), а не из `PublicationModel.metadata`.
7. Google Sheets — источник публикации, не зеркало состояния GreenMarket.
   Обратная синхронизация в Stage 1 не реализуется.

## Последствия

- Требуются изменения в уже смёрженных PR-004 (`StructureValidator`,
  `BusinessValidator`), PR-005 (`Mapper`, `PublicationMetadata`), PR-006
  (`PublicationService.publish()`, `PublicationResult`) — не только новый
  PR-007.
- Обновляются нормативные документы: `Catalog_Template.md`,
  `Publication_Model.md`, `Publication_Service.md`, `REST_API.md`.
- Excel в будущем — отдельный `Parser`, работающий уже по этой (новой)
  модели публикации, а не по старой генерируемой.
- `Validator.validate()` теряет параметр `seller_id` (ничего в
  `Validator`/`BusinessValidator` больше в нём не нуждается; `Mapper.map()`
  сохраняет собственный явный параметр `seller_id`, не затронут).

## Связанные документы

`docs/02-domain/Catalog_Template.md`, `docs/02-domain/Publication_Model.md`,
`docs/04-services/Publication_Service.md`, `docs/04-services/REST_API.md`.

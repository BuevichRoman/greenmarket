// GreenMarket Product Card — цикл 2 (docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md)
// Container-bound script: привязан к рабочей книге продавца (Seller Workspace).

var API_BASE_URL = 'https://CHANGE_ME.example.com/api/v1'; // TODO: заменить на реальный адрес backend перед деплоем

var CATALOG_SHEET_NAME = 'Каталог';
var GROUPS_SHEET_NAME = 'Товарные группы';
var PRODUCTS_SHEET_NAME = 'Товарные позиции';
var OTHER_PRODUCT_PLACEHOLDER = 'Прочее';
var ACCESS_TOKEN_PROPERTY = 'GREENMARKET_ACCESS_TOKEN';
var CURRENT_ROW_PROPERTY = 'GREENMARKET_CURRENT_ROW';

// Порядок точно соответствует CATALOG_COLUMNS в backend/app/validation/structure_validator.py —
// не менять без синхронной правки backend-контракта.
var COLUMN_ORDER = [
  'SellerProductId',
  'Наименование продавца',
  'Товарная группа GreenMarket',
  'Товарная позиция GreenMarket',
  'Цена',
  'Единица продажи',
  'Остаток',
  'Описание',
  'Дополнительные характеристики',
  'Фото',
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addToUi();
}

function openCardForSelectedRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var rowIndex = sheet.getActiveCell().getRow();
  if (rowIndex < 2) {
    SpreadsheetApp.getUi().alert('Выделите строку товара в листе «Каталог» (не строку заголовка).');
    return;
  }
  showCard(rowIndex);
}

function openCardForNewRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  showCard(sheet.getLastRow() + 1);
}

function showCard(rowIndex) {
  PropertiesService.getDocumentProperties().setProperty(CURRENT_ROW_PROPERTY, String(rowIndex));
  var html = HtmlService.createHtmlOutputFromFile('Card').setWidth(520).setHeight(640);
  SpreadsheetApp.getUi().showModalDialog(html, 'Карточка товара');
}

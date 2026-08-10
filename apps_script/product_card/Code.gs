// GreenMarket Product Card — цикл 2 (docs/superpowers/specs/2026-07-22-product-card-apps-script-design.md)
// Container-bound script: привязан к рабочей книге продавца (Seller Workspace).

var API_BASE_URL = 'https://CHANGE_ME.example.com/api/v1'; // TODO: заменить на реальный адрес backend перед деплоем
var SELLER_CABINET_URL = 'https://CHANGE_ME.example.com/seller/'; // TODO: заменить на реальный адрес Seller Cabinet перед деплоем

var CATALOG_SHEET_NAME = 'Каталог';
var GROUPS_SHEET_NAME = 'Товарные группы';
var PRODUCTS_SHEET_NAME = 'Товарные позиции';
var OTHER_PRODUCT_PLACEHOLDER = 'Прочее';
var ACCESS_TOKEN_PROPERTY = 'GREENMARKET_ACCESS_TOKEN';
var CURRENT_ROW_PROPERTY = 'GREENMARKET_CURRENT_ROW';
var LAST_PRODUCT_GROUP_PROPERTY = 'GREENMARKET_LAST_PRODUCT_GROUP';

// Справочник единиц продажи — для начала фиксированный список (не отдельный лист),
// т.к. состав редко меняется. Старое значение ячейки, которого нет в списке,
// всё равно не теряется — populateSelectWithFallback на стороне Card.html.
var UNIT_OPTIONS = ['шт.', 'кг', 'упаковка', 'коробка'];

// Порядок точно соответствует CATALOG_COLUMNS в backend/app/validation/structure_validator.py —
// не менять без синхронной правки backend-контракта.
var COLUMN_ORDER = [
  'SellerProductId',
  'Название товара',
  'Товарная группа GreenMarket',
  'Товарная позиция GreenMarket',
  'Цена',
  'Единица продажи',
  'Остаток',
  'Описание',
  'Дополнительные характеристики',
  'Фото',
  'Страна происхождения',
  'Дата поставки',
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addItem('Личный кабинет', 'openSellerCabinet')
    .addToUi();
}

function openCardForSelectedRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var rowIndex = sheet.getActiveCell().getRow();
  if (rowIndex < 2) {
    SpreadsheetApp.getUi().alert('Выделите строку товара в листе «Каталог» (не строку заголовка).');
    return;
  }
  // «Открыть карточку» должна открывать только существующий товар — если строка
  // пустая, это не тот товар, который продавец хотел открыть (по фидбеку коллеги
  // 2026-07-24: раньше здесь молча создавалась новая карточка под видом «открытия»).
  if (!rowHasProductData(sheet, rowIndex)) {
    SpreadsheetApp.getUi().alert(
      'В выбранной строке ещё нет товара. Чтобы открыть карточку существующего товара — ' +
      'выделите строку с данными. Чтобы добавить новый товар — используйте «Добавить товар».'
    );
    return;
  }
  showCard(rowIndex);
}

function openCardForNewRow() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  showCard(sheet.getLastRow() + 1);
}

function rowHasProductData(sheet, rowIndex) {
  var values = sheet.getRange(rowIndex, 1, 1, COLUMN_ORDER.length).getValues()[0];
  return values.some(function (value) { return value !== '' && value !== null; });
}

function showCard(rowIndex) {
  PropertiesService.getDocumentProperties().setProperty(CURRENT_ROW_PROPERTY, String(rowIndex));
  var html = HtmlService.createHtmlOutputFromFile('Card').setWidth(680).setHeight(760);
  SpreadsheetApp.getUi().showModalDialog(html, 'Карточка товара');
}

function getCardData() {
  var rowIndex = Number(PropertiesService.getDocumentProperties().getProperty(CURRENT_ROW_PROPERTY));
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var lastRow = sheet.getLastRow();
  var isNewRow = rowIndex > lastRow;

  var rawRow = isNewRow
    ? COLUMN_ORDER.map(function () { return ''; })
    : sheet.getRange(rowIndex, 1, 1, COLUMN_ORDER.length).getValues()[0];

  var fields = {};
  COLUMN_ORDER.forEach(function (name, i) { fields[name] = rawRow[i]; });
  fields['Дата поставки'] = formatDateForInput(fields['Дата поставки']);

  if (isNewRow) {
    // Продавец обычно добавляет несколько товаров одной группы подряд —
    // подставляем группу с предыдущей сохранённой карточки.
    var lastGroup = PropertiesService.getDocumentProperties().getProperty(LAST_PRODUCT_GROUP_PROPERTY);
    if (lastGroup) fields['Товарная группа GreenMarket'] = lastGroup;
  }

  var referenceLists = getReferenceLists();

  return {
    rowIndex: rowIndex,
    isNewRow: isNewRow,
    fields: fields,
    photoIds: parsePhotoIds(fields['Фото']),
    groups: referenceLists.groups,
    products: referenceLists.products,
    units: UNIT_OPTIONS,
  };
}

function getReferenceLists() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var groups = readColumnValues(ss.getSheetByName(GROUPS_SHEET_NAME), 3);
  var products = readColumnValues(ss.getSheetByName(PRODUCTS_SHEET_NAME), 3);
  products.push(OTHER_PRODUCT_PLACEHOLDER);
  return { groups: groups, products: products };
}

function readColumnValues(sheet, columnIndex) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  return sheet.getRange(2, columnIndex, lastRow - 1, 1).getValues()
    .map(function (row) { return row[0]; })
    .filter(function (value) { return value !== '' && value !== null; });
}

// Карточка отдаёт дату из <input type="date"> строкой «ГГГГ-ММ-ДД».
function parseIsoDateOrKeep(value) {
  if (!value) return '';
  var parts = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!parts) return value;
  return new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
}

// Обратное преобразование: значение ячейки — для <input type="date">.
function formatDateForInput(cellValue) {
  if (!cellValue) return '';
  if (!(cellValue instanceof Date)) return String(cellValue);
  return Utilities.formatDate(cellValue, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function parsePhotoIds(cellValue) {
  if (!cellValue) return [];
  return String(cellValue)
    .split(';')
    .map(function (part) { return part.trim(); })
    .filter(function (part) { return part !== ''; })
    .map(function (part) { return Number(part); })
    .filter(function (id) { return !isNaN(id); });
}

// Сколько колонок листа «Каталог» реально объявлено заголовком. Книга шаблона
// 2.1 короче нынешнего COLUMN_ORDER на «Страну происхождения» и «Дату
// поставки» — новые необязательные колонки всегда добавляются только в хвост.
function columnCount(sheet) {
  var header = sheet.getRange(1, 1, 1, COLUMN_ORDER.length).getValues()[0];
  var declared = 0;
  while (declared < COLUMN_ORDER.length && header[declared] === COLUMN_ORDER[declared]) {
    declared++;
  }
  return declared;
}

function saveRow(rowIndex, formData) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CATALOG_SHEET_NAME);
  var existingSellerProductId = rowIndex <= sheet.getLastRow() ? sheet.getRange(rowIndex, 1).getValue() : '';

  var values = [
    existingSellerProductId, // Карточка никогда не пишет SellerProductId сама — служебное поле сервера.
    formData.sellerName,
    formData.productGroup,
    formData.productName,
    Number(formData.price), // Card.html передаёт value HTML input — это всегда строка, даже для type="number".
    formData.unit,
    Number(formData.stock), // Аналогично — приводим к числу перед записью в ячейку.
    formData.description,
    formData.attributes,
    formData.photoIds.join(';'),
    formData.originCountry,
    // Пишем настоящую дату, а не строку: тогда ячейка показывается в формате
    // книги продавца, а Sheets API отдаёт её серийным числом, которое сервер
    // разбирает (backend/app/parsing/cell_values.py). Непарсящееся значение
    // сохраняем как есть — ошибку про формат покажет публикация.
    parseIsoDateOrKeep(formData.supplyDate),
  ];

  // В книге шаблона 2.1 двух последних колонок физически нет. Записать их
  // всё равно означало бы положить страну и дату в безымянные колонки, откуда
  // публикация их не прочитает: продавец увидел бы «сохранено», а покупатель
  // ничего. Пишем ровно столько колонок, сколько объявлено в заголовке.
  var declared = columnCount(sheet);
  sheet.getRange(rowIndex, 1, 1, declared).setValues([values.slice(0, declared)]);

  if (formData.productGroup) {
    PropertiesService.getDocumentProperties().setProperty(LAST_PRODUCT_GROUP_PROPERTY, formData.productGroup);
  }
}

function getOrPromptAccessToken() {
  var props = PropertiesService.getDocumentProperties();
  var token = props.getProperty(ACCESS_TOKEN_PROPERTY);
  if (token) return token;

  var ui = SpreadsheetApp.getUi();
  var result = ui.prompt(
    'Активация доступа',
    'Введите код активации, полученный от администратора GreenMarket:',
    ui.ButtonSet.OK_CANCEL
  );
  if (result.getSelectedButton() !== ui.Button.OK) return null;

  var activationCode = result.getResponseText().trim();
  if (!activationCode) return null;

  token = activateAccess_(activationCode);
  if (!token) {
    ui.alert('Код активации недействителен, просрочен или уже использован. Обратитесь к администратору за новым кодом.');
    return null;
  }

  props.setProperty(ACCESS_TOKEN_PROPERTY, token);
  return token;
}

function activateAccess_(activationCode) {
  var response = UrlFetchApp.fetch(API_BASE_URL + '/seller/activate', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      activation_code: activationCode,
      spreadsheet_id: SpreadsheetApp.getActiveSpreadsheet().getId(),
    }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) return null;
  return JSON.parse(response.getContentText()).access_token;
}

function handleApiResponse(response, expectedStatus) {
  var code = response.getResponseCode();
  var body;
  try {
    body = JSON.parse(response.getContentText());
  } catch (e) {
    // Не-JSON ответ (например, HTML-страница ошибки от прокси перед backend) —
    // сообщение читаемее, чем сырой SyntaxError.
    throw new Error('Сервер вернул некорректный ответ (код ' + code + ')');
  }
  if (code === expectedStatus) return body;

  if (code === 403) {
    PropertiesService.getDocumentProperties().deleteProperty(ACCESS_TOKEN_PROPERTY);
  }
  var message = (body.error && body.error.message) || ('Ошибка сервера (' + code + ')');
  throw new Error(message);
}

function uploadPhoto(base64Data, contentType, filename) {
  var accessToken = getOrPromptAccessToken();
  if (!accessToken) {
    throw new Error('Доступ не активирован — загрузка отменена.');
  }

  var bytes = Utilities.base64Decode(base64Data);
  var blob = Utilities.newBlob(bytes, contentType, filename || 'photo');

  var response = UrlFetchApp.fetch(API_BASE_URL + '/photos', {
    method: 'post',
    payload: {
      access_token: accessToken,
      file: blob,
    },
    muteHttpExceptions: true,
  });

  return handleApiResponse(response, 201).photo_id;
}

function getPhotoUrls(photoIds) {
  if (!photoIds || photoIds.length === 0) return [];

  var accessToken = getOrPromptAccessToken();
  if (!accessToken) {
    throw new Error('Доступ не активирован — превью недоступно.');
  }

  var url = API_BASE_URL + '/photos?ids=' + photoIds.join(',') + '&access_token=' + encodeURIComponent(accessToken);
  var response = UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true });
  return handleApiResponse(response, 200).photos;
}

// Единственное действие, которое не ходит в API само, — поэтому мёртвый токен здесь
// никогда не чистился через handleApiResponse, и продавец получал ссылку, которая
// молча не работает. Проверяем токен перед выдачей ссылки.
function openSellerCabinet() {
  var token = getOrPromptAccessToken();
  if (!token) return;

  if (isAccessTokenRejected_(token)) {
    PropertiesService.getDocumentProperties().deleteProperty(ACCESS_TOKEN_PROPERTY);
    SpreadsheetApp.getUi().alert('Сохранённый доступ к GreenMarket больше не действует. Введите новый код активации.');
    token = getOrPromptAccessToken(); // свойство очищено — запросит код заново
    if (!token) return;
  }

  var url = SELLER_CABINET_URL + '?token=' + encodeURIComponent(token);
  var html = HtmlService
    .createHtmlOutput('<a href="' + url + '" target="_blank">Открыть личный кабинет</a>')
    .setWidth(320)
    .setHeight(80);
  SpreadsheetApp.getUi().showModalDialog(html, 'Личный кабинет');
}

// Отзываем токен только на явный 403 — сетевой сбой или 5xx на стороне сервера
// не повод заставлять продавца заново активировать книгу.
function isAccessTokenRejected_(token) {
  var url = API_BASE_URL + '/seller/catalog?access_token=' + encodeURIComponent(token);
  try {
    return UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true }).getResponseCode() === 403;
  } catch (e) {
    return false;
  }
}

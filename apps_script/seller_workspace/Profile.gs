// GreenMarket Seller Profile — форма профиля продавца в рабочей книге
// (docs/superpowers/specs/2026-08-07-seller-profile-form-apps-script-design.md).
// Тот же container-bound проект, что и карточка товара: API_BASE_URL,
// getOrPromptAccessToken() и handleApiResponse() объявлены в Code.gs.

// Состав полей дублирует backend/app/profile/fields.py (PROFILE_FIELDS) — источник
// правды там. Stage 2 добавит фото, логотип и соцсети (Seller_Profile.md, раздел 4):
// новое поле придётся завести и здесь, и в ProfileForm.html.
var PROFILE_FIELDS = ['phone', 'whatsapp', 'market_id', 'row', 'place', 'working_hours', 'short_description'];

var PROFILE_FIELD_LABELS = {
  phone: 'телефон',
  whatsapp: 'WhatsApp',
  market_id: 'место торговли',
  row: 'ряд',
  place: 'место',
  working_hours: 'часы работы',
  short_description: 'краткое описание',
};

// Форма лежит в ProfileForm.html, а не в Profile.html: Apps Script требует уникальные
// имена файлов независимо от типа, и HTML-файл «Profile» рядом со скриптом «Profile»
// создать нельзя — редактор отвечает «Файл с таким названием уже существует».
function openSellerProfile() {
  if (!getOrPromptAccessToken()) return; // код активации не введён — диалог не открываем
  var html = HtmlService.createHtmlOutputFromFile('ProfileForm').setWidth(560).setHeight(700);
  SpreadsheetApp.getUi().showModalDialog(html, 'Профиль продавца');
}

// Внутри открытого диалога код активации не запрашиваем: ui.prompt вытеснил бы
// форму вместе с введённым текстом (Sheets держит одно модальное окно). Токен
// кладёт openSellerProfile() до открытия диалога; исчезнуть он может только если
// handleApiResponse стёр его на 403 — тогда просим переоткрыть форму.
function requireAccessToken_() {
  var token = PropertiesService.getDocumentProperties().getProperty(ACCESS_TOKEN_PROPERTY);
  if (!token) {
    throw new Error('Доступ к GreenMarket больше не действует. Закройте окно и откройте «Профиль продавца» заново — книга запросит код активации.');
  }
  return token;
}

// Профиль и справочник мест торговли одним вызовом: диалогу нужно и то, и
// другое, чтобы отрисовать выпадающий список с уже выбранным значением, а два
// последовательных google.script.run показали бы форму дважды недособранной.
//
// profile — ответ Seller API как есть: {seller_id, name, status, market_id, row,
// place, working_hours, short_description, phone, whatsapp, suggested_phone}.
// markets — только открытые точки: {id, name, type, address}.
function getProfileData() {
  var accessToken = requireAccessToken_();

  var profileUrl = API_BASE_URL + '/seller/profile?access_token=' + encodeURIComponent(accessToken);
  var profile = handleApiResponse(
    UrlFetchApp.fetch(profileUrl, { method: 'get', muteHttpExceptions: true }), 200
  );

  var marketsUrl = API_BASE_URL + '/seller/markets?access_token=' + encodeURIComponent(accessToken);
  var markets = handleApiResponse(
    UrlFetchApp.fetch(marketsUrl, { method: 'get', muteHttpExceptions: true }), 200
  ).markets;

  return { profile: profile, markets: markets };
}

// changedFields — только реально изменённые поля (diff считает ProfileForm.html). PUT
// трактует отсутствие ключа как «не трогать», поэтому отправка всей формы затёрла бы
// правки администратора, сделанные пока диалог был открыт. Пустая строка — очистка поля.
// missingFields — незаполненные обязательные, нужны только для текста toast'а.
function saveProfile(changedFields, missingFields) {
  var accessToken = requireAccessToken_();

  // Белый список: у PUT extra="forbid", лишний ключ в теле — это 422, а не игнор.
  var payload = { access_token: accessToken };
  PROFILE_FIELDS.forEach(function (name) {
    if (changedFields.hasOwnProperty(name)) payload[name] = changedFields[name];
  });

  var response = UrlFetchApp.fetch(API_BASE_URL + '/seller/profile', {
    method: 'put',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  var changed = handleApiResponse(response, 200).changed;

  // toast() вызывается здесь, на сервере, ещё до возврата значения — диалог закрывает
  // сама форма позже, в своём success-handler'е. Toast висит 8 секунд и переживает
  // закрытие диалога, так что сообщение в любом случае остаётся видно в таблице.
  SpreadsheetApp.getActiveSpreadsheet().toast(profileSavedMessage_(missingFields), 'GreenMarket', 8);
  return changed;
}

function profileSavedMessage_(missingFields) {
  if (!missingFields || missingFields.length === 0) return 'Профиль сохранён.';
  var names = missingFields.map(function (name) { return PROFILE_FIELD_LABELS[name]; });
  return 'Профиль сохранён. Покупатель не увидит: ' + names.join(', ') + '.';
}

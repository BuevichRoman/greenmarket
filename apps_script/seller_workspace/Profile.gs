// GreenMarket Seller Profile — форма профиля продавца в рабочей книге
// (docs/superpowers/specs/2026-08-07-seller-profile-form-apps-script-design.md).
// Тот же container-bound проект, что и карточка товара: API_BASE_URL,
// getOrPromptAccessToken() и handleApiResponse() объявлены в Code.gs.

// Состав полей дублирует backend/app/profile/fields.py (PROFILE_FIELDS) — источник
// правды там. Stage 2 добавит фото, логотип и соцсети (Seller_Profile.md, раздел 4):
// новое поле придётся завести и здесь, и в Profile.html.
var PROFILE_FIELDS = ['phone', 'whatsapp', 'row', 'place', 'working_hours', 'short_description'];

var PROFILE_FIELD_LABELS = {
  phone: 'телефон',
  whatsapp: 'WhatsApp',
  row: 'ряд',
  place: 'место',
  working_hours: 'часы работы',
  short_description: 'краткое описание',
};

function openSellerProfile() {
  if (!getOrPromptAccessToken()) return; // код активации не введён — диалог не открываем
  var html = HtmlService.createHtmlOutputFromFile('Profile').setWidth(560).setHeight(700);
  SpreadsheetApp.getUi().showModalDialog(html, 'Профиль продавца');
}

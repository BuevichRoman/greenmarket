# Форма профиля продавца в рабочей книге (Apps Script) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Продавец заполняет свой профиль (телефон, WhatsApp, ряд, место, часы работы, краткое описание) прямо из рабочей книги — меню «GreenMarket» → «Профиль продавца» — вместо curl'а к готовому Seller API.

**Architecture:** Модальный диалог Apps Script в том же container-bound проекте, где живёт карточка товара. Данные не касаются листов книги: `GET /api/v1/seller/profile` при открытии, `PUT /api/v1/seller/profile` при сохранении, причём отправляются только изменённые поля. Бэкенд не меняется вообще — контракт задеплоен в PR #29.

**Tech Stack:** Google Apps Script (V8 runtime), HTML/CSS/vanilla JS. Ни строки Python.

---

## Перед стартом

Прочитать design doc целиком: [`docs/superpowers/specs/2026-08-07-seller-profile-form-apps-script-design.md`](../specs/2026-08-07-seller-profile-form-apps-script-design.md). Контракт эндпоинтов — [`docs/04-services/REST_API.md`](../../04-services/REST_API.md), строки про `GET`/`PUT /api/v1/seller/profile`. Состав полей и лимиты длины — `backend/app/profile/fields.py` (`PROFILE_FIELDS`), обязательность на Stage 1 — [`docs/02-domain/Seller_Profile.md`](../../02-domain/Seller_Profile.md) §5.

**Автоматических тестов в этом плане нет.** У Apps Script в репозитории нет ни раннера, ни тулинга (карточка товара покрыта тем же способом). Каждая задача — код + вычитывание + коммит; полная проверка руками на реальной книге против прода — Task 6, она же гейт готовности. Бэкенд не трогаем, его 450 тестов остаются зелёными без запуска.

Все пути — относительно корня репозитория. Работаем в ветке `seller-profile-form` (уже создана, в ней лежит design doc).

---

### Task 1: Переименование папки скрипта

**Files:**
- Rename: `apps_script/product_card/` → `apps_script/seller_workspace/`
- Modify: `apps_script/seller_workspace/README.md` (пути внутри)
- Modify: `docs/05-ui/Seller_Workspace_UX.md:121`

**Контекст:** Apps Script у книги ровно один, и профиль будет делить с карточкой глобальную область (`API_BASE_URL`, `getOrPromptAccessToken`, `handleApiResponse`). Папка должна называться по проекту, а не по одной его функции.

- [ ] **Step 1: Переименовать папку**

```bash
git mv apps_script/product_card apps_script/seller_workspace
```

- [ ] **Step 2: Поправить пути внутри README**

В `apps_script/seller_workspace/README.md` заменить три вхождения `apps_script/product_card/` на `apps_script/seller_workspace/` (строки с `appsscript.json`, `Code.gs`, `Card.html` в разделе «Деплой»).

- [ ] **Step 3: Поправить ссылку в нормативном документе**

В `docs/05-ui/Seller_Workspace_UX.md`, раздел 12 («Карточка товара»), заменить:

```text
`apps_script/product_card/README.md` и
```

на:

```text
`apps_script/seller_workspace/README.md` и
```

- [ ] **Step 4: Проверить, что живых ссылок на старый путь не осталось**

Run: `grep -rn "apps_script/product_card" --exclude-dir=.git --exclude-dir=kwork .`
Expected: совпадения только в `docs/superpowers/plans/2026-07-22-*.md`, `docs/superpowers/plans/2026-07-23-*.md` и `docs/superpowers/specs/2026-07-2*.md` — это исторические документы, они описывают состояние на свою дату и **не правятся**. Ни одного совпадения в `apps_script/`, `docs/05-ui/`, `docs/04-services/`.

- [ ] **Step 5: Commit**

```bash
git add -A apps_script docs/05-ui/Seller_Workspace_UX.md
git commit -m "Папка Apps Script названа по проекту книги, а не по карточке товара"
```

---

### Task 2: Пункт меню и открытие диалога

**Files:**
- Modify: `apps_script/seller_workspace/Code.gs:35-42` (функция `onOpen`)
- Create: `apps_script/seller_workspace/Profile.gs`

- [ ] **Step 1: Добавить пункт в меню**

В `apps_script/seller_workspace/Code.gs` заменить `onOpen`:

```javascript
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GreenMarket')
    .addItem('Открыть карточку', 'openCardForSelectedRow')
    .addItem('Добавить товар', 'openCardForNewRow')
    .addItem('Профиль продавца', 'openSellerProfile')
    .addItem('Личный кабинет', 'openSellerCabinet')
    .addToUi();
}
```

- [ ] **Step 2: Создать `Profile.gs` с константами и открытием диалога**

Создать `apps_script/seller_workspace/Profile.gs`:

```javascript
// GreenMarket Seller Profile — форма профиля продавца в рабочей книге
// (docs/superpowers/specs/2026-08-07-seller-profile-form-apps-script-design.md).
// Тот же container-bound проект, что и карточка товара: API_BASE_URL,
// getOrPromptAccessToken() и handleApiResponse() объявлены в Code.gs.

// Состав полей дублирует backend/app/profile/fields.py (PROFILE_FIELDS) — источник
// правды там. Stage 2 добавит фото, логотип и соцсети (Seller_Profile.md, раздел 4):
// новое поле придётся завести и здесь, и в ProfileForm.html.
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
  var html = HtmlService.createHtmlOutputFromFile('ProfileForm').setWidth(560).setHeight(700);
  SpreadsheetApp.getUi().showModalDialog(html, 'Профиль продавца');
}
```

- [ ] **Step 3: Самопроверка**

Вычитать: имя файла в `createHtmlOutputFromFile('ProfileForm')` совпадает с именем HTML-файла, который создаётся в Task 5 (`ProfileForm.html` в репозитории — файл `ProfileForm` в Script Editor). Имя не `Profile`: Apps Script требует уникальные имена файлов независимо от типа, и HTML `Profile` рядом со скриптом `Profile` создать нельзя. `getOrPromptAccessToken` объявлена в `Code.gs:163` и возвращает `null` при отказе/неверном коде — поэтому проверка `if (!...) return;` достаточна, свой alert здесь не нужен (его уже показывает `getOrPromptAccessToken`).

- [ ] **Step 4: Commit**

```bash
git add apps_script/seller_workspace/Code.gs apps_script/seller_workspace/Profile.gs
git commit -m "Меню книги продавца получает пункт «Профиль продавца»"
```

---

### Task 3: Чтение профиля с сервера

**Files:**
- Modify: `apps_script/seller_workspace/Profile.gs`

- [ ] **Step 1: Добавить `getProfileData`**

Дописать в конец `apps_script/seller_workspace/Profile.gs`:

```javascript
// Ответ отдаётся форме как есть: {seller_id, name, status, row, place, working_hours,
// short_description, phone, whatsapp, suggested_phone}.
function getProfileData() {
  var accessToken = getOrPromptAccessToken();
  if (!accessToken) throw new Error('Доступ не активирован — профиль недоступен.');

  var url = API_BASE_URL + '/seller/profile?access_token=' + encodeURIComponent(accessToken);
  var response = UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true });
  return handleApiResponse(response, 200);
}
```

- [ ] **Step 2: Самопроверка**

Сверить с `docs/04-services/REST_API.md` (строка про `GET /api/v1/seller/profile`): токен передаётся query-параметром `access_token`, успешный код — 200. `handleApiResponse` (`Code.gs:203`) сама разбирает конверт ошибки, чистит сохранённый токен на 403 и бросает `Error` с человекочитаемым сообщением — своей обработки кодов здесь быть не должно.

- [ ] **Step 3: Commit**

```bash
git add apps_script/seller_workspace/Profile.gs
git commit -m "Книга продавца читает профиль через Seller API"
```

---

### Task 4: Сохранение профиля

**Files:**
- Modify: `apps_script/seller_workspace/Profile.gs`

- [ ] **Step 1: Добавить `saveProfile` и `profileSavedMessage_`**

Дописать в конец `apps_script/seller_workspace/Profile.gs`:

```javascript
// changedFields — только реально изменённые поля (diff считает ProfileForm.html). PUT
// трактует отсутствие ключа как «не трогать», поэтому отправка всей формы затёрла бы
// правки администратора, сделанные пока диалог был открыт. Пустая строка — очистка поля.
// missingFields — незаполненные обязательные, нужны только для текста toast'а.
function saveProfile(changedFields, missingFields) {
  var accessToken = getOrPromptAccessToken();
  if (!accessToken) throw new Error('Доступ не активирован — сохранение отменено.');

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

  // Диалог к моменту показа toast'а уже закрыт формой — сообщение видно в самой таблице.
  SpreadsheetApp.getActiveSpreadsheet().toast(profileSavedMessage_(missingFields), 'GreenMarket', 8);
  return changed;
}

function profileSavedMessage_(missingFields) {
  if (!missingFields || missingFields.length === 0) return 'Профиль сохранён.';
  var names = missingFields.map(function (name) { return PROFILE_FIELD_LABELS[name]; });
  return 'Профиль сохранён. Покупатель не увидит: ' + names.join(', ') + '.';
}
```

- [ ] **Step 2: Самопроверка**

Сверить с `docs/04-services/REST_API.md` (строка про `PUT /api/v1/seller/profile`): тело — JSON с `access_token` и подмножеством полей профиля, ответ — `{"changed": [...]}`, код 200. Проверить, что ключи в `PROFILE_FIELDS` дословно совпадают с именами полей в `backend/app/profile/fields.py` (`row`, `place`, `working_hours`, `short_description`, `phone`, `whatsapp`) — опечатка здесь даёт 422 `VALIDATION_ERROR`, а не молчаливый игнор.

- [ ] **Step 3: Commit**

```bash
git add apps_script/seller_workspace/Profile.gs
git commit -m "Книга продавца сохраняет профиль, отправляя только изменённые поля"
```

---

### Task 5: Форма (`ProfileForm.html`)

**Files:**
- Create: `apps_script/seller_workspace/ProfileForm.html`

- [ ] **Step 1: Создать файл формы**

Создать `apps_script/seller_workspace/ProfileForm.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; font-size: 16px; }
    label { display: block; margin-top: 14px; font-weight: bold; }
    input[type="text"], textarea {
      width: 100%; padding: 10px; box-sizing: border-box; margin-top: 6px;
      font-size: 15px; font-family: Arial, sans-serif;
    }
    .header { border-bottom: 1px solid #ddd; padding-bottom: 12px; }
    .header .name { font-size: 18px; font-weight: bold; }
    .header .status { color: #888; font-size: 13px; margin-top: 4px; }
    .hint { font-weight: normal; color: #888; font-size: 13px; }
    .suggest { margin-top: 6px; font-size: 13px; color: #666; }
    .suggest button {
      background: none; border: none; color: #2a7a2a; cursor: pointer;
      font-size: 13px; padding: 0; text-decoration: underline;
    }
    .warning { margin-top: 16px; color: #a06000; font-size: 13px; }
    .actions { margin-top: 20px; display: flex; gap: 10px; }
    button.primary { background: #2a7a2a; color: #fff; border: none; padding: 12px 22px; border-radius: 4px; cursor: pointer; font-size: 15px; }
    button.secondary { background: #eee; border: 1px solid #ccc; padding: 12px 22px; border-radius: 4px; cursor: pointer; font-size: 15px; }
    #status { margin-top: 12px; color: #888; font-size: 13px; }
  </style>
</head>
<body>
  <div class="header">
    <div class="name" id="sellerName"></div>
    <div class="status" id="sellerStatus"></div>
  </div>

  <label>Телефон <span class="hint">— обязательно</span></label>
  <input type="text" id="phone" maxlength="255">
  <div class="suggest" id="phoneSuggest" style="display: none;">
    В учётной записи указан <span id="suggestedPhone"></span> —
    <button type="button" onclick="useSuggestedPhone()">подставить</button>
  </div>

  <label>WhatsApp <span class="hint">— обязательно</span></label>
  <input type="text" id="whatsapp" maxlength="255">

  <label>Ряд <span class="hint">— обязательно</span></label>
  <input type="text" id="row" maxlength="255">

  <label>Место <span class="hint">— обязательно</span></label>
  <input type="text" id="place" maxlength="255">

  <label>Часы работы <span class="hint">— обязательно, например 09:00–18:00</span></label>
  <input type="text" id="working_hours" maxlength="255">

  <label>Краткое описание <span class="hint">— не обязательно</span></label>
  <textarea id="short_description" rows="3" maxlength="2000"></textarea>

  <div class="warning" id="warning"></div>

  <div class="actions">
    <button class="primary" id="saveButton" onclick="save()">Сохранить</button>
    <button class="secondary" onclick="google.script.host.close()">Отмена</button>
  </div>
  <div id="status"></div>

  <script>
    // FIELDS дублирует PROFILE_FIELDS в Profile.gs и backend/app/profile/fields.py,
    // REQUIRED_FIELDS — обязательные поля Stage 1 из Seller_Profile.md, раздел 5.
    // maxlength у полей выше равны лимитам оттуда же: 255 (users_prop_items_varchar)
    // и 2000 (продуктовый лимит краткого описания).
    var FIELDS = ['phone', 'whatsapp', 'row', 'place', 'working_hours', 'short_description'];
    var REQUIRED_FIELDS = ['phone', 'whatsapp', 'row', 'place', 'working_hours'];
    var LABELS = {
      phone: 'телефон',
      whatsapp: 'WhatsApp',
      row: 'ряд',
      place: 'место',
      working_hours: 'часы работы',
    };

    var loaded = {};           // значения с сервера на момент открытия — база для diff
    var suggestedPhone = null; // учётный телефон платформы, если профильный ещё пуст

    function setStatus(text) {
      document.getElementById('status').textContent = text || '';
    }

    function value(name) {
      return document.getElementById(name).value.trim();
    }

    function fillForm(data) {
      document.getElementById('sellerName').textContent = data.name || '';
      document.getElementById('sellerStatus').textContent =
        (data.status === 'ACTIVE' ? 'Активен' : 'Временно деактивирован') +
        ' · название и статус меняет администратор';

      FIELDS.forEach(function (name) {
        var initial = (data[name] === null || data[name] === undefined) ? '' : String(data[name]);
        loaded[name] = initial;
        var element = document.getElementById(name);
        element.value = initial;
        element.addEventListener('input', refreshHints);
      });

      suggestedPhone = data.suggested_phone || null;
      refreshHints();
    }

    // Телефон профиля — витринный контакт, его видит покупатель; учётный номер
    // платформы подставляется только по явному клику (design doc, решение 3).
    function useSuggestedPhone() {
      document.getElementById('phone').value = suggestedPhone;
      refreshHints();
    }

    function missingFields() {
      return REQUIRED_FIELDS.filter(function (name) { return value(name) === ''; });
    }

    function refreshHints() {
      var showSuggest = Boolean(suggestedPhone) && value('phone') === '';
      document.getElementById('suggestedPhone').textContent = suggestedPhone || '';
      document.getElementById('phoneSuggest').style.display = showSuggest ? 'block' : 'none';

      var missing = missingFields();
      document.getElementById('warning').textContent = missing.length === 0
        ? ''
        : 'Покупатель не увидит: ' + missing.map(function (name) { return LABELS[name]; }).join(', ') + '.';
    }

    function buildDiff() {
      var diff = {};
      FIELDS.forEach(function (name) {
        if (value(name) !== loaded[name]) diff[name] = value(name);
      });
      return diff;
    }

    function save() {
      var diff = buildDiff();
      if (Object.keys(diff).length === 0) {
        setStatus('Изменений нет.');
        return;
      }
      setStatus('Сохранение…');
      document.getElementById('saveButton').disabled = true;
      google.script.run
        .withSuccessHandler(function () {
          google.script.host.close();
        })
        .withFailureHandler(function (err) {
          // Форма остаётся открытой: это единственное место, где живёт введённый текст.
          setStatus('');
          document.getElementById('saveButton').disabled = false;
          alert('Ошибка сохранения: ' + err.message);
        })
        .saveProfile(diff, missingFields());
    }

    setStatus('Загрузка профиля…');
    google.script.run
      .withSuccessHandler(function (data) {
        fillForm(data);
        setStatus('');
      })
      .withFailureHandler(function (err) {
        setStatus('');
        alert('Не удалось загрузить профиль: ' + err.message);
      })
      .getProfileData();
  </script>
</body>
</html>
```

- [ ] **Step 2: Самопроверка**

Проверить построчно:

- `id` каждого поля дословно совпадает с именем поля контракта (`phone`, `whatsapp`, `row`, `place`, `working_hours`, `short_description`) — на этом равенстве держатся `value()`, `buildDiff()` и `loaded`;
- `FIELDS` и `REQUIRED_FIELDS` совпадают с `PROFILE_FIELDS` в `Profile.gs` и `PROFILE_FIELDS`/§5 на бэкенде; `LABELS` покрывает все `REQUIRED_FIELDS` (иначе в предупреждении будет `undefined`);
- имена серверных функций в `google.script.run` (`getProfileData`, `saveProfile`) совпадают с объявленными в `Profile.gs`;
- `buildDiff` сравнивает с `loaded`, а не с пустой строкой — иначе при открытии-сохранении без правок уедет вся форма.

- [ ] **Step 3: Commit**

```bash
git add apps_script/seller_workspace/ProfileForm.html
git commit -m "Форма профиля продавца: подсказка учётного телефона, предупреждение о пустых полях"
```

---

### Task 6: README, деплой в книгу и ручной прогон

**Files:**
- Modify: `apps_script/seller_workspace/README.md`

**Контекст:** это гейт готовности — до прохождения чек-листа задача не считается сделанной. Рабочая книга — `12fOFHg9iyJWNSm4LpvL2K3Z9hZQV1-RcQLXuJef1Ku4`, backend — `https://testapi.vnespecplanpodaz.online/api/v1`.

- [ ] **Step 1: Дополнить раздел «Деплой»**

В `apps_script/seller_workspace/README.md` после шага про создание HTML-файла `Card` добавить два шага:

```markdown
7. Создать файл `Profile.gs` (`Файл → Создать → Скрипт`, имя ровно `Profile`) —
   вставить содержимое `apps_script/seller_workspace/Profile.gs`.
8. Создать HTML-файл `ProfileForm` (`Файл → Создать → HTML-файл`, имя ровно
   `ProfileForm`) — вставить содержимое `apps_script/seller_workspace/ProfileForm.html`.
   Имя отличается от `Profile.gs` не случайно: Apps Script требует уникальные имена
   файлов независимо от типа и на `Profile` ответит «Файл с таким названием уже
   существует».
```

Существующий последний шаг («Сохранить проект … в меню должен появиться пункт «GreenMarket»») перенумеровать соответственно.

- [ ] **Step 2: Добавить заголовок к существующему чек-листу**

Перед первым пунктом существующего чек-листа ручного тестирования вставить строку `### Карточка товара`, чтобы к нему можно было добавить второй раздел.

- [ ] **Step 3: Добавить чек-лист профиля**

В конец раздела «Ручное тестирование (чек-лист)» добавить:

```markdown
### Профиль продавца

- [ ] В меню «GreenMarket» есть пункт «Профиль продавца».
- [ ] На неактивированной книге пункт спрашивает код активации; отказ (Cancel) —
      диалог не открывается, ошибок нет.
- [ ] Диалог показывает реальные значения профиля этого продавца; название продавца
      и статус — только для чтения (полей ввода для них нет).
- [ ] Профиль без телефона у продавца с учётным номером в платформе — под полем
      «Телефон» видна подсказка «В учётной записи указан … — подставить»; клик
      подставляет номер в поле, но пока не нажато «Сохранить», на сервере ничего
      не меняется (проверить `GET /api/v1/seller/profile`).
- [ ] Профиль с заполненным телефоном — подсказки нет.
- [ ] Изменение одного поля → «Сохранить» → диалог закрывается, в таблице toast
      «Профиль сохранён», а `GET /api/v1/seller/profile` отдаёт новое значение.
- [ ] Повторное «Сохранить» без правок — статус «Изменений нет», запрос к API не уходит
      (проверить по журналу выполнений Apps Script), диалог остаётся открытым.
- [ ] Изменения видны покупателю: `GET /api/v1/catalog/sellers/{id}` отдаёт новые значения.
- [ ] Изменения попали в ленту: `GET /api/v1/admin/profile-changes` (с токеном админа)
      содержит запись с `author_role = "SELLER"` и именами изменённых полей.
- [ ] Очистка заполненного поля (стереть текст → «Сохранить») — поле пустое и в
      `GET /api/v1/seller/profile`, и в карточке покупателя.
- [ ] Незаполненные обязательные поля — в форме под кнопками строка «Покупатель не увидит: …»,
      она же в toast'е после сохранения; кнопка «Сохранить» при этом работает.
- [ ] Деактивация продавца администратором (`PUT /api/v1/admin/sellers/{id}/deactivate`) →
      следующее сохранение даёт alert с ошибкой доступа, форма остаётся открытой с введённым
      текстом, сохранённый токен стёрт — следующее действие в книге снова спросит код активации.
- [ ] Недоступный backend (временно указать неверный `API_BASE_URL`) — alert об ошибке,
      введённые данные в форме не потеряны.
```

- [ ] **Step 4: Задеплоить в рабочую книгу и пройти чек-лист**

Перенести `Code.gs`, `Profile.gs`, `ProfileForm.html` в Script Editor книги (`API_BASE_URL` в книге уже указывает на прод — заменять не нужно, если файл `Code.gs` копируется целиком, поставить реальный адрес заново). Пройти **весь** чек-лист раздела «Профиль продавца» и убедиться, что карточка товара не сломалась: открыть «Открыть карточку» на заполненной строке — форма загружается как раньше.

Отмечать пункты фактически пройденными, а не «должно работать». Любое расхождение — правка кода и повторный прогон затронутых пунктов.

- [ ] **Step 5: Commit**

```bash
git add apps_script/seller_workspace/README.md
git commit -m "README книги продавца: деплой и чек-лист формы профиля"
```

---

### Task 7: Нормативные документы

**Files:**
- Modify: `docs/05-ui/Seller_Workspace.md:60`, `:65`, `:128`
- Modify: `docs/05-ui/Seller_Workspace_UX.md` (новый раздел 13)
- Modify: `docs/02-domain/Seller_Profile.md` (последний абзац)

**Контекст:** три документа утверждают, что продавец профиль не редактирует. Это было верно до PR #29 и перестало быть верным сейчас. Документы нормативные и уходили коллеге — правки точечные, без переписывания разделов.

- [ ] **Step 1: `Seller_Workspace.md`, раздел 6 — первый абзац**

Заменить абзац (строка 60):

```text
**В Seller Workspace v1.0 этого листа нет.** Решение принято по итогам ревью ТЗ-010: карточка продавца в Customer UI Stage 1 строится напрямую из [Seller_Profile.md](../02-domain/Seller_Profile.md) (базы данных), поэтому дублирующая витрина профиля внутри рабочей книги на первом этапе не даёт продавцу никакой новой возможности — он её не редактирует, а Publication Pipeline её не читает. Добавление такого листа только увеличило бы количество мест, где хранится одна и та же информация, без функциональной необходимости.
```

на:

```text
**В Seller Workspace v1.0 этого листа нет.** Решение принято по итогам ревью ТЗ-010: карточка продавца в Customer UI Stage 1 строится напрямую из [Seller_Profile.md](../02-domain/Seller_Profile.md) (базы данных), а дублирующая витрина профиля внутри рабочей книги хранила бы одну и ту же информацию в двух местах без функциональной необходимости — Publication Pipeline её не читает. Продавец правит профиль из книги с 2026-08-07, но не листом: модальной формой Apps Script («GreenMarket» → «Профиль продавца», [Seller_Workspace_UX.md](Seller_Workspace_UX.md) раздел 13), которая читает и пишет профиль через Seller API и в листах книги ничего не хранит.
```

- [ ] **Step 2: `Seller_Workspace.md`, раздел 6 — второй пункт списка**

Заменить (строка 65):

```text
- лист должен быть полностью защищён от редактирования продавцом — редактирование профиля прямо исключено из объёма Seller_Profile.md (раздел 11);
```

на:

```text
- лист должен быть полностью защищён от редактирования продавцом: профиль правится формой Apps Script через Seller API, и второй путь правки через ячейки книги создал бы два источника одних и тех же значений;
```

- [ ] **Step 3: `Seller_Workspace.md` — запись в журнал изменений**

В разделе 12 («Версионирование») перед записью `**2026-08-02:**` вставить:

```text
**2026-08-07:** продавец редактирует свой профиль (телефон, WhatsApp, ряд, место, часы работы, краткое описание) из рабочей книги — модальной формой Apps Script, а не листом. Структура книги и `TemplateVersion` не меняются: значения хранятся платформенным механизмом свойств пользователя ([Seller_Profile.md](../02-domain/Seller_Profile.md), раздел 10a), в листах книги профиля по-прежнему нет. Прежняя формулировка раздела 6 «продавец профиль не редактирует» относилась к состоянию до появления Seller API профиля (PR #29).
```

- [ ] **Step 4: `Seller_Workspace_UX.md` — новый раздел 13**

Добавить в конец документа (после раздела 12 «Карточка товара»):

```markdown
## 13. Профиль продавца (Apps Script)

Меню «GreenMarket» → «Профиль продавца» открывает модальную форму профиля: телефон,
WhatsApp, ряд, место, часы работы, краткое описание. Название продавца и статус показаны
только для чтения — их меняет администратор. Форма ничего не хранит в листах книги:
значения читаются и пишутся через `GET`/`PUT /api/v1/seller/profile`, отправляются только
изменённые поля. Поля, обязательные на Stage 1 ([Seller_Profile.md](../02-domain/Seller_Profile.md),
раздел 5), помечены в форме; незаполненные не блокируют сохранение, но форма предупреждает,
что покупатель их не увидит. Учётный телефон платформы предлагается подсказкой и
подставляется только по явному действию продавца — витринный контакт отделён от учётного
(Seller_Profile.md, раздел 10a). Полное описание архитектуры, деплоя и ручного тестирования —
`apps_script/seller_workspace/README.md` и
`docs/superpowers/specs/2026-08-07-seller-profile-form-apps-script-design.md`.
```

- [ ] **Step 5: `Seller_Profile.md` — последний абзац**

Заменить последний абзац документа:

```text
[Seller_Workspace.md](../05-ui/Seller_Workspace.md) (ТЗ-010) фиксирует, что рабочая книга продавца (Google Sheets) не отображает и не редактирует Seller Profile в Stage 1 — карточка продавца в Customer UI строится из этой модели напрямую, отдельного листа «Профиль продавца» в Seller Workspace v1.0 нет (зарезервировано на будущее).
```

на:

```text
[Seller_Workspace.md](../05-ui/Seller_Workspace.md) (ТЗ-010) фиксирует, что отдельного листа «Профиль продавца» в рабочей книге Stage 1 нет (зарезервировано на будущее) — карточка продавца в Customer UI строится из этой модели напрямую. При этом с 2026-08-07 продавец правит профиль из книги: модальной формой Apps Script («GreenMarket» → «Профиль продавца»), которая ходит в `GET`/`PUT /api/v1/seller/profile` и в листах книги ничего не хранит.
```

- [ ] **Step 6: Проверить, что противоречий не осталось**

Run: `grep -rn "не редактирует\|редактирование профиля прямо исключено" docs/02-domain/Seller_Profile.md docs/05-ui/Seller_Workspace.md docs/05-ui/Seller_Workspace_UX.md`
Expected: ни одного совпадения.

- [ ] **Step 7: Commit**

```bash
git add docs/02-domain/Seller_Profile.md docs/05-ui/Seller_Workspace.md docs/05-ui/Seller_Workspace_UX.md
git commit -m "Нормативка: продавец правит профиль из книги формой, а не листом"
```

---

## Готовность

- [ ] Чек-лист «Профиль продавца» из `apps_script/seller_workspace/README.md` пройден целиком на реальной книге против прода (Task 6).
- [ ] Карточка товара после переименования папки и правки `Code.gs` работает как раньше.
- [ ] `grep -rn "apps_script/product_card" --exclude-dir=.git --exclude-dir=kwork .` не даёт совпадений вне исторических планов и спек от 2026-07-22/23.
- [ ] Бэкенд не изменён: `git diff main --stat -- backend/` пуст.
- [ ] PR открыт, в описании — ссылка на design doc и результат ручного прогона.

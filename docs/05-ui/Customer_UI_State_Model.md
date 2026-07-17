# GreenMarket Customer UI State Model — Покупатель (Stage 1)

**Version:** 1.0
**Status:** Draft (черновик, ещё не отправлен на ревью коллеге)

**Основание:** [Customer_UI_UX.md](Customer_UI_UX.md) (сценарий, из которого выведены состояния и переходы). Подготовлен по рекомендации коллеги (17.07.2026, ChatGPT-ссылка `t_6a5a51b3b71c8191a200191b52aa9d7f`) — не переходить сразу к реализации экранов, а сначала формализовать состояния интерфейса как мост между UX и будущей реализацией ViewModel/FSM.

**Разграничение с [Customer_UI_UX.md](Customer_UI_UX.md):** UX-документ описывает сценарий с точки зрения покупателя (что видит, как перемещается, как сравнивает предложения); настоящий документ формализует то же самое как состояния интерфейса и переходы между ними. Поведение здесь не переопределяется, только формализуется.

**Разграничение с Customer UI FSM (Platform Core):** по разбивке подсистем от 13.07.2026 полноценный «Customer UI FSM» — часть подсистемы Platform Core, вне рамок этого документа. State Model — более лёгкий мост между UX и будущей ViewModel/FSM-реализацией, не заменяет и не предвосхищает архитектуру Platform Core FSM.

## 1. Назначение

Формализовать состояния интерфейса покупателя Buyer Web Stage 1 и переходы между ними — основу для реализации ViewModel.

## 2. Область ответственности

Документ определяет:

- полный список состояний интерфейса покупателя Stage 1;
- переходы между состояниями (событие → следующее состояние);
- текущее отображение каждого состояния на экранах [Customer_UI_UX.md](Customer_UI_UX.md) в Stage 1 (справочно, не определение).

Документ не определяет: как каждое состояние выглядит визуально (UI Design Specification, вне рамок [Buyer_MVP.md](Buyer_MVP.md)); внутреннюю реализацию ViewModel/FSM; retry-политику при восстановлении сети (открытый вопрос, раздел 6).

## 3. Состояния

Состояние — первичная сущность этой модели; экран — лишь то, как это состояние в данный момент отображается в Stage 1. Если навигация Customer UI изменится (экраны объединятся, разделятся или появятся новые), состояния и переходы это не потребует пересматривать — изменится только то, какой экран что показывает.

| Состояние | Текущее отображение (Stage 1) | Описание |
|---|---|---|
| `Initial` | Главная | Точка входа, до первого запроса к API |
| `Loading` | — | Ожидание ответа API. Общее для всех запросов (категории/поиск-каталог/карточка товара) — какой конкретно запрос выполняется, не моделируется отдельным состоянием, это деталь реализации ViewModel. **Осознанное упрощение Stage 1, не универсальная архитектура**: при дальнейшем развитии разным операциям может понадобиться собственное состояние загрузки (например, разный UI для скелетона каталога и спиннера карточки товара) |
| `CategoriesLoaded` | Главная | Дерево категорий и популярные категории получены |
| `SearchResults` | Каталог товаров | Список товаров по поиску или категории получен, результаты не пусты |
| `EmptySearch` | Каталог товаров | Поиск или категория не дали результатов |
| `ProductOpened` | Карточка товара | Предложения продавцов по товару получены. **Последнее состояние happy path Stage 1** — дальнейшее взаимодействие с продавцом находится вне области ответственности Customer UI Stage 1 (см. раздел 4) |
| `Error` | — | Последний запрос завершился ошибкой API |
| `Offline` | — | Нет сети |

## 4. Таблица переходов

| Из | Событие | В |
|---|---|---|
| `Initial` | `onAppStart` (запрос категорий) | `Loading` |
| `Loading` | `onCategoriesSuccess` | `CategoriesLoaded` |
| `Loading` | `onCategoriesError` | `Error` |
| `Loading` | `onOffline` | `Offline` |
| `CategoriesLoaded` | `onSearchSubmit` / `onCategorySelect` | `Loading` |
| `SearchResults` | `onSearchSubmit` / `onCategorySelect` (уточнение прямо на экране, без возврата на «Главная» — [Customer_UI_UX.md](Customer_UI_UX.md), раздел 5) | `Loading` |
| `EmptySearch` | `onSearchSubmit` / `onCategorySelect` | `Loading` |
| `Loading` | `onSearchSuccess` (есть результаты) | `SearchResults` |
| `Loading` | `onSearchEmpty` (результатов нет) | `EmptySearch` |
| `Loading` | `onSearchError` | `Error` |
| `SearchResults` | `onProductOpen` | `Loading` |
| `Loading` | `onProductSuccess` | `ProductOpened` |
| `Loading` | `onProductError` | `Error` |
| `ProductOpened` | `onBack` | `SearchResults` или `EmptySearch` — то состояние, из которого товар был открыт (см. раздел 6, пункт 2) |
| `Error` | `onRetry` | `Loading` (повтор последнего запроса) |
| `Offline` | `onNetworkRestored` | `Loading` (повтор последнего запроса) |

**`ProductOpened` является последним состоянием happy path Stage 1; дальнейшее взаимодействие с продавцом (контакт, оформление заказа, доставка, оплата) находится вне области ответственности Customer UI Stage 1.** Отсюда нет исходящего перехода дальше — прямое следствие закрытого решения [Customer_UI_UX.md](Customer_UI_UX.md) (раздел 3, шаг 6).

## 5. Схема (обзор)

Запуск и загрузка категорий:

```
Initial ──onAppStart──> Loading ──onCategoriesSuccess──> CategoriesLoaded
                            ├──onCategoriesError──> Error
                            └──onOffline──> Offline
```

Поиск и каталог товаров (из `CategoriesLoaded`, `SearchResults` или `EmptySearch`):

```
CategoriesLoaded ─┐
SearchResults ─────┼──onSearchSubmit / onCategorySelect──> Loading ──onSearchSuccess──> SearchResults
EmptySearch ───────┘                                          ├──onSearchEmpty──> EmptySearch
                                                                └──onSearchError──> Error
```

Карточка товара и возврат:

```
SearchResults ──onProductOpen──> Loading ──onProductSuccess──> ProductOpened
                                     └──onProductError──> Error

ProductOpened ──onBack──> SearchResults / EmptySearch (откуда был открыт товар)
```

Восстановление после ошибки/офлайна:

```
Error ────onRetry────────> Loading (повтор последнего запроса)
Offline ──onNetworkRestored──> Loading (повтор последнего запроса)
```

## 6. Открытые вопросы

1. **Retry при восстановлении сети** (`Offline` → `onNetworkRestored`) — автоматический или требует действия покупателя. [Buyer_MVP.md](Buyer_MVP.md) офлайн-поведение вообще не описывает — не додумано.
2. **Куда именно ведёт `onBack` из `ProductOpened`** — в `SearchResults` или в `EmptySearch`, зависит от того, из какого состояния был открыт товар. ViewModel должен где-то хранить это как «предыдущее состояние» — механизм хранения (стек состояний, просто последнее значение) не специфицирован здесь, это деталь реализации.
3. **Состояние при обновлении/повторном открытии страницы** — в Stage 1 нет персистентности сессии ([Customer_UI_UX.md](Customer_UI_UX.md), раздел 4: нет авторизации, нет истории). Предположительно `Initial`, но это вывод из отсутствия персонализации, а не отдельно зафиксированное решение — требует подтверждения при реализации.

## 7. Связанные документы

- [Customer_UI_UX.md](Customer_UI_UX.md) — сценарий покупателя, из которого выведены состояния и переходы.
- [Buyer_MVP.md](Buyer_MVP.md) — структурный контракт экранов Stage 1.
- [REST_API.md](../04-services/REST_API.md) — контракт Catalog API (не реализован, см. [Customer_UI_UX.md](Customer_UI_UX.md), раздел 10, пункт 2).

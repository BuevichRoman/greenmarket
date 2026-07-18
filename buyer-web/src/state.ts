// Состояния и переходы — точное соответствие
// docs/05-ui/Customer_UI_State_Model.md (раздел 3-4). Loading общий для всех
// запросов (осознанное упрощение Stage 1, см. документ) — какой конкретно
// запрос выполняется, хранится в `pending` (деталь реализации ViewModel, не
// специфицирована документом).

import type { ProductDetail, ProductGroup, ProductListItem, SearchQuery } from './types'

export type Status =
  | 'Initial'
  | 'Loading'
  | 'CategoriesLoaded'
  | 'SearchResults'
  | 'EmptySearch'
  | 'ProductOpened'
  | 'Error'
  | 'Offline'

export type PendingRequest =
  | { kind: 'categories' }
  | { kind: 'search'; query: SearchQuery; page: number }
  | { kind: 'product'; id: number }

interface ListData {
  query: SearchQuery
  products: ProductListItem[]
  page: number
  total: number
}

export interface AppState {
  status: Status
  categories: ProductGroup[]
  list: ListData | null
  emptyQuery: SearchQuery | null
  product: ProductDetail | null
  // Открытый вопрос §6.2 документа (куда ведёт onBack из ProductOpened) —
  // решено запоминанием, из какого listing-состояния был открыт товар.
  previousListStatus: 'SearchResults' | 'EmptySearch' | null
  errorMessage: string | null
  pending: PendingRequest | null
}

export type Action =
  | { type: 'onAppStart' }
  | { type: 'onCategoriesSuccess'; categories: ProductGroup[] }
  | { type: 'onCategoriesError'; message: string }
  | { type: 'onOffline' }
  | { type: 'onSearchSubmit'; query: SearchQuery }
  | { type: 'onCategorySelect'; groupId: number }
  | { type: 'onSearchSuccess'; products: ProductListItem[]; page: number; total: number }
  | { type: 'onSearchEmpty' }
  | { type: 'onSearchError'; message: string }
  | { type: 'onProductOpen'; productId: number }
  | { type: 'onProductSuccess'; product: ProductDetail }
  | { type: 'onProductError'; message: string }
  | { type: 'onBack' }
  | { type: 'onRetry' }
  | { type: 'onNetworkRestored' }
  // Не из State Model — чисто навигационное удобство (клик по лого), не меняет
  // данные и не требует нового запроса: категории уже загружены в state.
  | { type: 'onGoHome' }

export const initialState: AppState = {
  status: 'Initial',
  categories: [],
  list: null,
  emptyQuery: null,
  product: null,
  previousListStatus: null,
  errorMessage: null,
  pending: null,
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'onAppStart':
      return { ...state, status: 'Loading', pending: { kind: 'categories' } }

    case 'onCategoriesSuccess':
      return { ...state, status: 'CategoriesLoaded', categories: action.categories, pending: null }

    case 'onSearchSubmit':
      return { ...state, status: 'Loading', pending: { kind: 'search', query: action.query, page: 1 } }

    case 'onCategorySelect':
      return {
        ...state,
        status: 'Loading',
        pending: { kind: 'search', query: { groupId: action.groupId, sort: 'name' }, page: 1 },
      }

    case 'onSearchSuccess':
      if (state.pending?.kind !== 'search') return state
      return {
        ...state,
        status: 'SearchResults',
        list: { query: state.pending.query, products: action.products, page: action.page, total: action.total },
        pending: null,
      }

    case 'onSearchEmpty':
      if (state.pending?.kind !== 'search') return state
      return { ...state, status: 'EmptySearch', emptyQuery: state.pending.query, list: null, pending: null }

    case 'onProductOpen':
      return {
        ...state,
        status: 'Loading',
        pending: { kind: 'product', id: action.productId },
        previousListStatus: state.status === 'EmptySearch' ? 'EmptySearch' : 'SearchResults',
      }

    case 'onProductSuccess':
      return { ...state, status: 'ProductOpened', product: action.product, pending: null }

    case 'onBack':
      return { ...state, status: state.previousListStatus ?? 'CategoriesLoaded', product: null }

    case 'onCategoriesError':
    case 'onSearchError':
    case 'onProductError':
      return { ...state, status: 'Error', errorMessage: action.message }

    case 'onOffline':
      return { ...state, status: 'Offline' }

    case 'onRetry':
    case 'onNetworkRestored':
      return { ...state, status: 'Loading' }

    case 'onGoHome':
      return { ...state, status: 'CategoriesLoaded', product: null, list: null, emptyQuery: null }

    default:
      return state
  }
}

import { useEffect, useReducer } from 'react'
import { fetchGroups, fetchProduct, fetchProducts } from './api'
import { initialState, reducer } from './state'
import type { SearchQuery } from './types'
import { HomeScreen } from './screens/HomeScreen'
import { CatalogScreen } from './screens/CatalogScreen'
import { ProductScreen } from './screens/ProductScreen'

function App() {
  const [state, dispatch] = useReducer(reducer, initialState)

  // Старт приложения — запрос категорий (Initial → Loading, State Model §4).
  useEffect(() => {
    dispatch({ type: 'onAppStart' })
  }, [])

  // onOffline/onNetworkRestored — реальные события браузера, не опрос.
  useEffect(() => {
    const goOffline = () => dispatch({ type: 'onOffline' })
    const goOnline = () => dispatch({ type: 'onNetworkRestored' })
    window.addEventListener('offline', goOffline)
    window.addEventListener('online', goOnline)
    return () => {
      window.removeEventListener('offline', goOffline)
      window.removeEventListener('online', goOnline)
    }
  }, [])

  // Единственное место, выполняющее сетевые запросы — реагирует на `pending`,
  // выставленный редьюсером при переходе в Loading (см. state.ts).
  useEffect(() => {
    if (state.status !== 'Loading' || !state.pending) return
    const pending = state.pending
    let cancelled = false

    async function run() {
      try {
        if (pending.kind === 'categories') {
          const { groups } = await fetchGroups()
          if (!cancelled) dispatch({ type: 'onCategoriesSuccess', categories: groups })
        } else if (pending.kind === 'search') {
          const { products, total } = await fetchProducts(pending.query, pending.page)
          if (cancelled) return
          if (products.length === 0) dispatch({ type: 'onSearchEmpty' })
          else dispatch({ type: 'onSearchSuccess', products, page: pending.page, total })
        } else {
          const product = await fetchProduct(pending.id)
          if (!cancelled) dispatch({ type: 'onProductSuccess', product })
        }
      } catch (err) {
        if (cancelled) return
        if (!navigator.onLine) {
          dispatch({ type: 'onOffline' })
          return
        }
        const message = err instanceof Error ? err.message : 'Неизвестная ошибка'
        const errorType = pending.kind === 'categories' ? 'onCategoriesError' : pending.kind === 'search' ? 'onSearchError' : 'onProductError'
        dispatch({ type: errorType, message })
      }
    }

    run()
    return () => {
      cancelled = true
    }
  }, [state.status, state.pending])

  function handleSearch(text: string) {
    const query: SearchQuery = { search: text, sort: 'name' }
    dispatch({ type: 'onSearchSubmit', query })
  }

  function handleSortChange(sort: SearchQuery['sort']) {
    if (!state.list) return
    dispatch({ type: 'onSearchSubmit', query: { ...state.list.query, sort } })
  }

  return (
    <div className="app">
      <header className="app-header">
        <button type="button" className="logo" onClick={() => dispatch({ type: 'onGoHome' })}>
          🥬 GreenMarket
        </button>
      </header>

      <main>
        {state.status === 'Loading' && <p className="loading-state">Загрузка…</p>}

        {state.status === 'Offline' && <p className="offline-state">Нет соединения с сетью. Ждём восстановления…</p>}

        {state.status === 'Error' && (
          <div className="error-state">
            <p>{state.errorMessage ?? 'Что-то пошло не так.'}</p>
            <button type="button" onClick={() => dispatch({ type: 'onRetry' })}>
              Повторить
            </button>
          </div>
        )}

        {state.status === 'CategoriesLoaded' && (
          <HomeScreen
            groups={state.categories}
            onSearch={handleSearch}
            onSelectCategory={(groupId) => dispatch({ type: 'onCategorySelect', groupId })}
          />
        )}

        {(state.status === 'SearchResults' || state.status === 'EmptySearch') && (
          <CatalogScreen
            groups={state.categories}
            query={state.status === 'SearchResults' ? state.list!.query : state.emptyQuery!}
            products={state.status === 'SearchResults' ? state.list!.products : []}
            total={state.status === 'SearchResults' ? state.list!.total : 0}
            onSearch={handleSearch}
            onSelectCategory={(groupId) => dispatch({ type: 'onCategorySelect', groupId })}
            onSortChange={handleSortChange}
            onOpenProduct={(productId) => dispatch({ type: 'onProductOpen', productId })}
          />
        )}

        {state.status === 'ProductOpened' && state.product && (
          <ProductScreen product={state.product} onBack={() => dispatch({ type: 'onBack' })} />
        )}
      </main>
    </div>
  )
}

export default App

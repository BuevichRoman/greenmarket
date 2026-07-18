import type { ProductGroup, ProductListItem, SearchQuery } from '../types'
import { SearchBar } from '../components/SearchBar'
import { CategoryTree } from '../components/CategoryTree'
import { ProductCard } from '../components/ProductCard'

interface Props {
  groups: ProductGroup[]
  query: SearchQuery
  products: ProductListItem[]
  total: number
  onSearch: (query: string) => void
  onSelectCategory: (groupId: number) => void
  onSortChange: (sort: SearchQuery['sort']) => void
  onOpenProduct: (id: number) => void
}

export function CatalogScreen({ groups, query, products, total, onSearch, onSelectCategory, onSortChange, onOpenProduct }: Props) {
  const activeGroup = groups.find((g) => g.id === query.groupId)

  return (
    <section className="screen catalog-screen">
      <SearchBar onSubmit={onSearch} initialValue={query.search} />

      <div className="catalog-layout">
        <aside className="catalog-sidebar">
          <h2>Категории</h2>
          <CategoryTree groups={groups} onSelect={onSelectCategory} />
        </aside>

        <div className="catalog-main">
          <div className="catalog-toolbar">
            <span className="catalog-heading">
              {activeGroup ? activeGroup.name : query.search ? `Поиск: «${query.search}»` : 'Все товары'}
              {total > 0 && <span className="catalog-total"> · {total}</span>}
            </span>
            <label className="sort-select">
              Сортировка:{' '}
              <select value={query.sort} onChange={(e) => onSortChange(e.target.value as SearchQuery['sort'])}>
                <option value="name">по названию</option>
                <option value="price">по цене</option>
              </select>
            </label>
          </div>

          {products.length === 0 ? (
            <p className="empty-state">Ничего не найдено. Попробуйте другой запрос или категорию.</p>
          ) : (
            <div className="product-grid">
              {products.map((p) => (
                <ProductCard key={p.id} product={p} onOpen={onOpenProduct} />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

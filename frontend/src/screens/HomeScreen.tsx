import type { ProductGroup } from '../types'
import { SearchBar } from '../components/SearchBar'
import { CategoryTree } from '../components/CategoryTree'

interface Props {
  groups: ProductGroup[]
  onSearch: (query: string) => void
  onSelectCategory: (groupId: number) => void
}

export function HomeScreen({ groups, onSearch, onSelectCategory }: Props) {
  const popular = [...groups]
    .sort((a, b) => b.product_count - a.product_count)
    .slice(0, 4)
    .filter((g) => g.product_count > 0)

  return (
    <section className="screen home-screen">
      <h1>GreenMarket</h1>
      <p className="tagline">Свежие продукты от местных фермеров</p>
      <SearchBar onSubmit={onSearch} />

      {popular.length > 0 && (
        <div className="popular-categories">
          {popular.map((g) => (
            <button key={g.id} type="button" className="chip" onClick={() => onSelectCategory(g.id)}>
              {g.name}
            </button>
          ))}
        </div>
      )}

      <h2>Категории</h2>
      <CategoryTree groups={groups} onSelect={onSelectCategory} />
    </section>
  )
}

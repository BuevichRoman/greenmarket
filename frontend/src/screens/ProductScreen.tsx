import type { ProductDetail } from '../types'
import { OfferCard } from '../components/OfferCard'

interface Props {
  product: ProductDetail
  onBack: () => void
}

export function ProductScreen({ product, onBack }: Props) {
  return (
    <section className="screen product-screen">
      <button type="button" className="back-link" onClick={onBack}>
        ← Назад
      </button>
      <h1>{product.name}</h1>
      {product.description && <p className="product-description">{product.description}</p>}

      <h2>Предложения продавцов ({product.offers.length})</h2>
      <ul className="offer-list">
        {product.offers.map((offer) => (
          <OfferCard key={offer.seller_product_id} offer={offer} />
        ))}
      </ul>
    </section>
  )
}

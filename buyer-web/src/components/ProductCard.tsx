import type { ProductListItem } from '../types'
import { formatPrice } from '../format'
import { PhotoPlaceholder } from './PhotoPlaceholder'

interface Props {
  product: ProductListItem
  onOpen: (id: number) => void
}

export function ProductCard({ product, onOpen }: Props) {
  return (
    <button type="button" className="product-card" onClick={() => onOpen(product.id)}>
      {product.photos.length > 0 ? (
        <img src={product.photos[0]} alt={product.name} className="product-photo" />
      ) : (
        <PhotoPlaceholder label={product.name} />
      )}
      <div className="product-card-body">
        <span className="product-name">{product.name}</span>
        <span className="product-price">от {formatPrice(product.min_price)}</span>
        <span className="product-offers">
          {product.offer_count} {product.offer_count === 1 ? 'продавец' : 'продавца'}
        </span>
      </div>
    </button>
  )
}

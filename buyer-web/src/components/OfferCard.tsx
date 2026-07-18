import type { SellerOffer } from '../types'
import { formatPrice, formatStock } from '../format'
import { PhotoPlaceholder } from './PhotoPlaceholder'

export function OfferCard({ offer }: { offer: SellerOffer }) {
  return (
    <li className="offer-card">
      {offer.photos.length > 0 ? (
        <img src={offer.photos[0]} alt={offer.seller_name} className="offer-photo" />
      ) : (
        <PhotoPlaceholder label={offer.seller_name} />
      )}
      <div className="offer-body">
        <span className="offer-seller">{offer.seller_name}</span>
        <span className="offer-price">
          {formatPrice(offer.price)} / {offer.unit}
        </span>
        <span className="offer-stock">В наличии: {formatStock(offer.stock, offer.unit)}</span>
        {offer.description && <p className="offer-description">{offer.description}</p>}
      </div>
    </li>
  )
}

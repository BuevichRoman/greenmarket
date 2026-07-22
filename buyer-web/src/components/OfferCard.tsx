import { useState } from 'react'
import type { SellerOffer } from '../types'
import { formatPrice, formatStock } from '../format'
import { PhotoPlaceholder } from './PhotoPlaceholder'

export function OfferCard({ offer }: { offer: SellerOffer }) {
  const [activeIndex, setActiveIndex] = useState(0)

  return (
    <li className="offer-card">
      {offer.photos.length > 0 ? (
        <div className="offer-gallery">
          <img src={offer.photos[activeIndex]} alt={offer.seller_name} className="offer-photo" />
          {offer.photos.length > 1 && (
            <div className="offer-gallery-thumbs">
              {offer.photos.map((url, index) => (
                <img
                  key={url}
                  src={url}
                  alt=""
                  className={`offer-gallery-thumb${index === activeIndex ? ' offer-gallery-thumb-active' : ''}`}
                  onClick={() => setActiveIndex(index)}
                />
              ))}
            </div>
          )}
        </div>
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

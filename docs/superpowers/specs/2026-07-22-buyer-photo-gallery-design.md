# Design: Галерея фото у покупателя (цикл 4 — карточка товара продавца)

**Дата:** 2026-07-22
**Статус:** Approved (Roman), design для внутренней реализации — узкий scope, только `OfferCard.tsx`.

## Контекст

Цикл 3 подключил реальные URL фото в Catalog API, но `OfferCard.tsx` (список предложений продавцов на странице товара) рендерит только `photos[0]` — первое фото из массива, который backend уже отдаёт целиком. При реальном сквозном тесте (продавец «тестир», товар «Тунец», 2 загруженных фото через карточку) это стало заметно: покупатель видел только одно из двух фото. Роман подтвердил — покупатель должен видеть все фото, которые загружает продавец.

Backend-изменений не требуется: `SellerOffer.photos: string[]` в Catalog API уже содержит полный список URL, в правильном порядке (`sort_order` из `SellerProductPhoto`), проверено на реальных данных.

## Scope

**В объём:**
- `buyer-web/src/components/OfferCard.tsx` — показ всех фото предложения продавца через полосу миниатюр (вариант A из брейншторминга: большое фото + ряд маленьких превью под ним, клик по превью меняет большое фото).

**Вне объёма (сознательно):**
- `ProductCard.tsx` (плитки в сетке каталога) — там по-прежнему одно фото на плитку. Роман подтвердил при брейншторминге: галерея нужна только на странице товара, не в сетке.
- Любые изменения API/типов/backend — данные уже приходят полностью, менять нечего.
- Автотесты — во frontend этого проекта тестового раннера нет вообще (только `vite`/`tsc`/`oxlint`), заводить фреймворк ради одного компонента не нужно, это не соответствовало бы существующему паттерну проекта.

## Реализация

`OfferCard` получает локальный React state для индекса активного фото:

```tsx
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
```

**Поведение:**
- `photos.length === 0` — без изменений, `PhotoPlaceholder` как сейчас.
- `photos.length === 1` — большое фото без полосы миниатюр (миниатюры не нужны для одного фото).
- `photos.length > 1` — большое фото (`activeIndex`, старт с 0) + полоса миниатюр под ним; клик по миниатюре меняет `activeIndex` и подсвечивает активную рамкой.

**Стили** (`index.css`, новые классы, минимально):
- `.offer-gallery` — обёртка (flex-column)
- `.offer-gallery-thumbs` — flex-row, gap, миниатюры фиксированного размера (~48×48px, `object-fit: cover`)
- `.offer-gallery-thumb-active` — рамка акцентным цветом на активной миниатюре

## Тестирование

Автотестов нет (см. Scope). Проверка: `tsc -b` (сборка проходит), затем визуально в dev-сервере на реальном товаре «Тунец» (2 фото, уже опубликован на проде) — обе миниатюры видны, клик переключает большое фото.

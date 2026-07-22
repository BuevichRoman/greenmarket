# Галерея фото у покупателя Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показать покупателю все фото предложения продавца на странице товара (`OfferCard`), а не только первое.

**Architecture:** Локальный React state (`activeIndex`) в `OfferCard`; полоса миниатюр под основным фото, клик меняет активное. Никаких изменений backend/типов — `SellerOffer.photos: string[]` уже приходит полностью.

**Tech Stack:** React 19 + TypeScript, Vite, plain CSS (`index.css`), без тестового раннера (в проекте его нет вообще).

---

### Task 1: Галерея фото в OfferCard

**Files:**
- Modify: `buyer-web/src/components/OfferCard.tsx`
- Modify: `buyer-web/src/index.css:309-317`

- [ ] **Step 1: Заменить содержимое `OfferCard.tsx`**

Текущий файл (`buyer-web/src/components/OfferCard.tsx`):

```tsx
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
```

Заменить на:

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

`activeIndex` сбрасывается на 0 при каждом маунте компонента (нормально — список офферов не переиспользует инстансы между разными товарами, `key` в `ProductScreen.tsx` — `offer.seller_product_id`).

- [ ] **Step 2: Добавить CSS для галереи**

В `buyer-web/src/index.css`, сразу после блока `.offer-card .photo-placeholder, .offer-photo` (строка 317, `}`), добавить:

```css
.offer-gallery {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex-shrink: 0;
}

.offer-gallery-thumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  width: 72px;
}

.offer-gallery-thumb {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  object-fit: cover;
  cursor: pointer;
  border: 1.5px solid transparent;
  opacity: 0.7;
}

.offer-gallery-thumb-active {
  border-color: var(--accent);
  opacity: 1;
}
```

`.offer-photo` уже стилизован (72×72, `object-fit: cover`) блоком `.offer-card .photo-placeholder, .offer-photo` — он не меняется, просто теперь обёрнут в `.offer-gallery`.

- [ ] **Step 3: Проверить сборку**

Run: `cd buyer-web && npx tsc -b`
Expected: без ошибок (exit code 0), никакого вывода.

- [ ] **Step 4: Визуальная проверка на реальных данных**

Открыть dev-сервер buyer-web (`npm run dev` в `buyer-web/`) или прод (`http://104.171.133.95/buyer/`), перейти на товар «Тунец» (2 реальных фото, уже опубликован). Проверить:
- Основное фото отображается
- Под ним — 2 миниатюры, первая подсвечена рамкой
- Клик по второй миниатюре меняет основное фото и подсветку

- [ ] **Step 5: Commit**

```bash
git add buyer-web/src/components/OfferCard.tsx buyer-web/src/index.css
git commit -m "GreenMarket: Buyer Web — галерея всех фото предложения продавца"
```

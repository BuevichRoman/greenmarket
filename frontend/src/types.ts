// Точное отражение backend/app/api/v1/catalog_schemas.py — Decimal-поля
// (price/stock/min_price) FastAPI сериализует как строки, не числа.

export interface ProductGroup {
  id: number
  parent_id: number | null
  name: string
  sort_order: number
  product_count: number
}

export interface ProductGroupsResponse {
  groups: ProductGroup[]
}

export interface ProductListItem {
  id: number
  name: string
  min_price: string
  offer_count: number
  photos: string[]
}

export interface ProductListResponse {
  products: ProductListItem[]
  page: number
  limit: number
  total: number
}

export interface SellerOffer {
  seller_product_id: number
  seller_id: number
  seller_name: string
  price: string
  unit: string
  stock: string
  description: string | null
  photos: string[]
}

export interface ProductDetail {
  id: number
  name: string
  description: string | null
  offers: SellerOffer[]
}

export interface SearchQuery {
  groupId?: number
  search?: string
  sort: 'name' | 'price'
}

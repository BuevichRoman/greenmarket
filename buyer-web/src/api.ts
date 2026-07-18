import type { ProductDetail, ProductGroupsResponse, ProductListResponse, SearchQuery } from './types'

// В dev — относительный путь, Vite проксирует на localhost:8000 (vite.config.ts).
// Для прода — поменять на реальный адрес backend через .env (VITE_API_BASE),
// код запросов трогать не нужно.
const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1/catalog'

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message = body?.error?.message ?? `Запрос завершился ошибкой (${response.status})`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export function fetchGroups(): Promise<ProductGroupsResponse> {
  return request<ProductGroupsResponse>('/groups')
}

export function fetchProducts(query: SearchQuery, page = 1): Promise<ProductListResponse> {
  const params = new URLSearchParams()
  if (query.groupId != null) params.set('group_id', String(query.groupId))
  if (query.search) params.set('search', query.search)
  params.set('sort', query.sort)
  params.set('page', String(page))
  return request<ProductListResponse>(`/products?${params.toString()}`)
}

export function fetchProduct(id: number): Promise<ProductDetail> {
  return request<ProductDetail>(`/products/${id}`)
}

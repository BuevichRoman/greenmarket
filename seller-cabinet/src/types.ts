// Точное отражение backend/app/api/v1/schemas.py (PublicationRequest/Response,
// ErrorResponse) — единственный реально реализованный сейчас Publication API.

export interface PublicationRequest {
  access_token: string
  sheet_url?: string
  spreadsheet_id?: string
}

export interface PublicationSuccess {
  success: true
  publication_id: number
  created: number
  updated: number
  deactivated: number
  message: string
  mode: 'prod' | 'test'
}

export interface ValidationErrorDetail {
  sheet: string
  message: string
  row: number | null
  column: string | null
}

export interface ApiError {
  code: string
  message: string
  details: ValidationErrorDetail[]
}

export interface SellerStatus {
  seller_id: number
  is_active: boolean
  current_catalog_version: number
  published_product_count: number
  last_published_at: string | null
}

export interface PublicationHistoryItem {
  version: number
  published_at: string
  created: number
  updated: number
  deactivated: number
}

export interface PublicationHistoryResponse {
  publications: PublicationHistoryItem[]
}

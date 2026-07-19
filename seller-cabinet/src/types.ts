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

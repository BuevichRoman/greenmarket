import type {
  ApiError,
  PublicationHistoryResponse,
  PublicationRequest,
  PublicationSuccess,
  SellerStatus,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

export type PublishResult = { ok: true; data: PublicationSuccess } | { ok: false; error: ApiError }

export async function publish(request: PublicationRequest): Promise<PublishResult> {
  const response = await fetch(`${API_BASE}/publications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  const body = await response.json()
  if (response.ok) {
    return { ok: true, data: body as PublicationSuccess }
  }
  return { ok: false, error: (body as { error: ApiError }).error }
}

export type SellerStatusResult = { ok: true; data: SellerStatus } | { ok: false; error: ApiError }
export type PublicationHistoryResult = { ok: true; data: PublicationHistoryResponse } | { ok: false; error: ApiError }

export async function fetchSellerStatus(accessToken: string): Promise<SellerStatusResult> {
  const response = await fetch(`${API_BASE}/seller/catalog?access_token=${encodeURIComponent(accessToken)}`)
  const body = await response.json()
  if (response.ok) {
    return { ok: true, data: body as SellerStatus }
  }
  return { ok: false, error: (body as { error: ApiError }).error }
}

export async function fetchPublicationHistory(accessToken: string): Promise<PublicationHistoryResult> {
  const response = await fetch(`${API_BASE}/publications?access_token=${encodeURIComponent(accessToken)}`)
  const body = await response.json()
  if (response.ok) {
    return { ok: true, data: body as PublicationHistoryResponse }
  }
  return { ok: false, error: (body as { error: ApiError }).error }
}

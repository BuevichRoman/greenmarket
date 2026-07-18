import type { ApiError, PublicationRequest, PublicationSuccess } from './types'

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

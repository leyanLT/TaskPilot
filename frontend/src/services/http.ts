const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')

export function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: unknown

  constructor(message: string, code: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return '操作失败，请稍后重试。'
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  // The assistant may legitimately spend up to two 30s model attempts plus
  // network overhead. A 90s ceiling avoids abandoning a request whose pending
  // action the server may still create.
  const timeout = window.setTimeout(() => controller.abort(), 90_000)
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(buildApiUrl(path), {
      ...init,
      headers,
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时，请稍后重试。', 'REQUEST_TIMEOUT', 0)
    }
    throw new ApiError('无法连接服务器，请确认后端已启动。', 'NETWORK_ERROR', 0)
  } finally {
    window.clearTimeout(timeout)
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError('服务器返回了无法解析的响应。', 'INVALID_RESPONSE', response.status)
    }
  }

  if (!response.ok) {
    const envelope = (payload ?? {}) as ErrorEnvelope
    throw new ApiError(
      envelope.error?.message || `请求失败（HTTP ${response.status}）。`,
      envelope.error?.code || 'REQUEST_FAILED',
      response.status,
      envelope.error?.details,
    )
  }

  return payload as T
}

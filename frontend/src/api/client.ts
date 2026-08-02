import axios, { type InternalAxiosRequestConfig } from 'axios'

// Porth API client — cookie/BFF mode (ADR-Z9, PORTH-531). The browser holds no
// token, only the http-only session cookie the Porth BFF set. `withCredentials`
// sends it on every request; the API answers CORS with Allow-Credentials.
//
// Ported from the Style Classifier admin client, which is the proven consumer of
// this contract. Deviating here is how you get a UI that reads but cannot write.
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// The API Gateway Lambda authorizer's identity source is the Authorization header,
// so a cookie-only request is 401'd by the gateway BEFORE the authorizer runs. We
// send an EMPTY bearer: the gateway then invokes the authorizer, which sees a blank
// token and falls through to the session-cookie path. The browser never holds a
// real token — this header exists purely to trigger authorizer invocation.
const EMPTY_BEARER = 'Bearer '

// CSRF: the authorizer requires the session's synchroniser token on cookie-authed
// mutating requests. Delivered to the SPA by GET /auth/me; fetched lazily and
// cached, since it is stable for the life of the session.
const MUTATING = new Set(['post', 'put', 'patch', 'delete'])

let _csrf: string | null = null

async function getCsrf(): Promise<string | null> {
  if (_csrf) return _csrf
  try {
    const r = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/auth/me`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    })
    if (r.ok) {
      _csrf = ((await r.json()) as { csrf_token?: string })?.csrf_token ?? null
    }
  } catch {
    /* leave null — the request itself will surface the auth error */
  }
  return _csrf
}

/** Drop the cached secret — call on logout so the next session fetches its own. */
export function clearCsrfCache(): void {
  _csrf = null
}

/**
 * Apply the cookie-mode auth headers. Shared with the sample-app client so the
 * two cannot drift — a client missing the empty bearer 401s at the gateway, and
 * one missing the CSRF header fails every write, both in ways that look like a
 * Porth fault rather than a client one.
 */
export async function applyCookieAuth(
  config: InternalAxiosRequestConfig,
): Promise<InternalAxiosRequestConfig> {
  config.headers.Authorization = EMPTY_BEARER
  if (MUTATING.has((config.method ?? 'get').toLowerCase())) {
    const csrf = await getCsrf()
    if (csrf) config.headers['X-CSRF-Token'] = csrf
  }
  return config
}

apiClient.interceptors.request.use(applyCookieAuth)

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail ?? err.response?.data?.message ?? err.message
    return Promise.reject(new Error(Array.isArray(detail) ? detail[0]?.msg : detail))
  },
)

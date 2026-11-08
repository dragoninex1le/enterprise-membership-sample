import axios, { type InternalAxiosRequestConfig } from 'axios'
import { browserHandle, clearSessionCsrf } from '@estyn/porth-admin/auth'
import { applyBrowserHandle } from './cookieAuth'
import { onAuthError } from '../lib/sessionExpiry'
import { authBaseUrl, porthApiBaseUrl } from '../lib/apiHost'

// Porth API client — cookie/BFF mode (ADR-Z9, PORTH-531). The browser holds no
// token, only the http-only session cookie the Porth BFF set; `withCredentials`
// attaches it. The API is served SAME-ORIGIN under /porth (a CloudFront
// behaviour strips the prefix — see template.yml), because a credentialed
// cross-origin call to Porth can never pass preflight: Porth answers
// Access-Control-Allow-Origin: * with no Allow-Credentials, and its allowed
// headers do not include X-CSRF-Token. Same arrangement as the Style Classifier
// admin app, the proven consumer of this contract. Deviating here is how you
// get a UI that reads but cannot write.
export const apiClient = axios.create({
  // PORTH-656: the API host's /porth on a tenant-API-host slot (lib/apiHost.ts).
  baseURL: porthApiBaseUrl(),
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// The session's CSRF secret, delivered by GET /auth/me; fetched lazily and cached,
// since it is stable for the life of the session. It is the key of the browser
// handle on EVERY call (cookieAuth.ts), and the X-CSRF-Token value on writes.
let _csrf: string | null = null

async function getCsrf(): Promise<string | null> {
  if (_csrf) return _csrf
  try {
    const r = await fetch(`${authBaseUrl()}/auth/me`, {
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
  clearSessionCsrf()
}

/**
 * Apply the cookie-mode auth headers: the browser handle in Authorization on every
 * call, and X-CSRF-Token on writes (cookieAuth.ts). Shared with the sample-app
 * client so the two cannot drift — a client without the handle is refused by
 * Porth's browser authorizer once API Gateway caches it (missing_handle), and one
 * without the CSRF header fails every write, both in ways that look like a Porth
 * fault rather than a client one.
 */
export async function applyCookieAuth(
  config: InternalAxiosRequestConfig,
): Promise<InternalAxiosRequestConfig> {
  return applyBrowserHandle(config, await getCsrf(), browserHandle)
}

apiClient.interceptors.request.use(applyCookieAuth)

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    // Dead session -> straight back through the BFF login (return_to = here);
    // never surface "authorizer denied: invalid_session" to the user.
    void onAuthError(err).catch(() => undefined)
    const detail = err.response?.data?.detail ?? err.response?.data?.message ?? err.message
    // The message is Porth's detail; the response stays on the error. A page tells "there is none yet"
    // (404) and "you may not" (403) from a fault by its status, and dropping it made every one a fault.
    return Promise.reject(Object.assign(new Error(Array.isArray(detail) ? detail[0]?.msg : detail), {
      response: err.response,
      status: err.response?.status as number | undefined,
    }))
  },
)

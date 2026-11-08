// The cookie-mode auth headers, kept apart from axios's instances so they can be
// tested without a browser (tests/unit/cookieAuth.test.ts).
//
// PORTH-655 (Components docs/INSTALL.md §5): every cookie-mode call carries the
// BROWSER HANDLE in Authorization:
//
//   handle = base64url( HMAC-SHA256( key = csrf_token from GET /porth/auth/me,
//                                    msg = host + "\n" + METHOD + "\n" + path ) )
//
// The session cookie still authenticates. The handle is what API Gateway caches
// Porth's browser-authorizer result under, so it must be unique to this session
// AND this route; the authorizer checks it against the session on every cache
// miss and refuses a call without one (missing_handle / invalid_handle) once the
// cache is on. It replaces the empty `Bearer ` this client used to send.

import type { InternalAxiosRequestConfig } from 'axios'

/** `browserHandle` from `@estyn/porth-admin/auth`, injectable for tests. */
export type BrowserHandle = (csrfSecret: string, url: string, method: string) => Promise<string>

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/**
 * The URL this request will go to, from the instance's `baseURL` and the call's `url`,
 * the way axios joins them. The handle covers the host and the path as sent
 * (`/porth/...`, `/sample/...`); the query string is not part of it.
 */
export function requestUrl(config: Pick<InternalAxiosRequestConfig, 'baseURL' | 'url'>): string {
  const url = config.url ?? ''
  if (/^[a-z][a-z\d+\-.]*:\/\//i.test(url) || !config.baseURL) return url
  return `${config.baseURL.replace(/\/+$/, '')}/${url.replace(/^\/+/, '')}`
}

/**
 * Set Authorization to the browser handle (and X-CSRF-Token on writes).
 *
 * With no CSRF secret — signed out, or /auth/me failed — no Authorization header at
 * all: never `Bearer ` with an empty value. The call is then refused as signed out,
 * which is what it is, and the session-expiry handler takes it from there.
 */
export async function applyBrowserHandle(
  config: InternalAxiosRequestConfig,
  csrf: string | null,
  handle: BrowserHandle,
): Promise<InternalAxiosRequestConfig> {
  const method = (config.method ?? 'get').toUpperCase()
  if (!csrf) {
    config.headers.delete('Authorization')
    return config
  }
  config.headers.set('Authorization', `Bearer ${await handle(csrf, requestUrl(config), method)}`)
  if (MUTATING.has(method)) config.headers.set('X-CSRF-Token', csrf)
  return config
}

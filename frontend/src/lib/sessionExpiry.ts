// Dead-session recovery (PORTH-531). Ported from the Style Classifier admin app,
// the proven consumer of this contract: a 401 from the API means the http-only
// session cookie no longer maps to a live session, and the only recovery is a
// fresh pass through the BFF login. Redirect once, carrying the current URL as
// return_to, rather than surfacing "authorizer denied: invalid_session" to the
// user as an opaque error string.
let redirecting = false

export function redirectToLogin(): void {
  if (redirecting) return
  redirecting = true
  const authBaseUrl = (import.meta.env.VITE_AUTH_BASE_URL ?? '').replace(/\/$/, '')
  const params = new URLSearchParams()
  params.set('return_to', window.location.href)
  window.location.assign(`${authBaseUrl}/auth/login?${params.toString()}`)
}

/** Axios response-interceptor rejection handler: redirect on 401, re-throw everything. */
export function onAuthError(error: unknown): Promise<never> {
  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 401) redirectToLogin()
  return Promise.reject(error)
}

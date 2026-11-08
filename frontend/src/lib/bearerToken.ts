// The session-bound bearer test (Porth ≥ 0.4.13, INSTALL.md "Session-bound bearer
// tokens" and §5). A signed-in page fetches its session's own IdP access token from
// GET /porth/auth/token and calls a bearer route on the same API host with it.
// Porth records each hand-out; after the session signs out its bearer authorizer
// refuses the token (session_ended), whatever the token's own exp says.
//
// The test page shows the token on purpose, so it can be copied before signing out
// and pasted back after: whether an old token still works is the question. Nothing
// here writes it anywhere — no storage, no console, no URL.

import { authBaseUrl, sampleApiBaseUrl } from './apiHost'

export interface SessionToken {
  access_token: string
  token_type: string
  expires_at: number
}

/** What one call came back with. status 0: no readable answer (see `unreadable`). */
export interface CallResult {
  status: number
  body: unknown
  unreadable?: string
  /** When the call was made, to find it in the authorizer log. */
  at?: string
}

export const WHOAMI_PATH = '/mcp/whoami'

/** The bearer route the test calls: the app's bearer API, on this page's API host. */
export function whoamiUrl(base: string = sampleApiBaseUrl()): string {
  return `${base.replace(/\/+$/, '')}${WHOAMI_PATH}`
}

/** Auth0's userinfo for the token's issuer: does the IdP itself still accept it? */
export function userinfoUrl(issuer: string): string {
  return `${issuer.replace(/\/+$/, '')}/userinfo`
}

/** A JWT's payload, or null for anything that is not one. Decoded, never verified. */
export function jwtClaims(token: string): Record<string, unknown> | null {
  const parts = token.trim().split('.')
  if (parts.length !== 3) return null
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4))
    const claims = JSON.parse(json)
    return claims && typeof claims === 'object' ? claims : null
  } catch {
    return null
  }
}

/** The same call from a terminal, for when the browser cannot read the answer. */
export function curlCommand(url: string, token: string): string {
  return `curl -sS -i -H 'Authorization: Bearer ${token.trim()}' '${url}'`
}

async function read(r: Response): Promise<unknown> {
  const text = await r.text()
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

const NO_CORS_ANSWER =
  'The browser could not read the answer. A refusal by the API gateway (an authorizer ' +
  'deny, typically 403) carries no CORS headers, so the page sees no status. Run the ' +
  'curl command below to see it, and the authorizer log gives the reason.'

/** GET /porth/auth/token, with a CSRF secret fetched fresh from /auth/me. */
export async function fetchSessionToken(): Promise<CallResult & { token?: SessionToken }> {
  const base = authBaseUrl()
  const me = await fetch(`${base}/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } })
  if (!me.ok) return { status: me.status, body: await read(me) }
  const csrf = ((await me.json()) as { csrf_token?: string }).csrf_token ?? ''
  const r = await fetch(`${base}/auth/token`, {
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-CSRF-Token': csrf },
  })
  const body = await read(r)
  return r.ok ? { status: r.status, body: null, token: body as SessionToken } : { status: r.status, body }
}

/** Call a bearer route with exactly this token: no cookie, no other credential. */
export async function callWithToken(url: string, token: string): Promise<CallResult> {
  const at = new Date().toISOString()
  try {
    const r = await fetch(url, {
      method: 'GET',
      credentials: 'omit',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token.trim()}` },
    })
    return { status: r.status, body: await read(r), at }
  } catch {
    return { status: 0, body: null, unreadable: NO_CORS_ANSWER, at }
  }
}

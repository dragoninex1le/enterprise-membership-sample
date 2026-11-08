// PORTH-654 — when the identity provider refuses a sign-in.
//
// Porth (0.4.14+) sends a refused sign-in back to the page that started it with two
// query parameters (Components docs/INSTALL.md §5):
//
//   login_error              e.g. access_denied
//   login_error_description  the identity provider's own words, e.g.
//                            "Not authorised for the platform console."
//
// The usual cause is a browser still signed in to Auth0 as another account. Porth has
// no UI, so the SPA asks whether to sign out. Both values are data from outside: they
// are only ever rendered as text.
//
// Signing out is a top-level navigation to Porth's logout on the API host, with this
// page as return_to. It ends the Auth0 session even when Porth holds no session for
// this browser, and on tenant API hosts it is the sign-out that works (Auth0 refuses a
// tenant UI origin as a logout return without organisation context).

import { authBaseUrl } from './apiHost'

export interface SignInRefusal {
  error: string
  description: string
}

const ERROR = 'login_error'
const DESCRIPTION = 'login_error_description'

let captured: SignInRefusal | null = null

/** The page's URL without the two refusal parameters. */
export function withoutRefusal(href: string): string {
  const url = new URL(href)
  url.searchParams.delete(ERROR)
  url.searchParams.delete(DESCRIPTION)
  return url.toString()
}

/**
 * Read the refusal from the address bar, once, at start-up — and take it out of the
 * address bar so a reload does not ask again.
 */
export function captureSignInRefusal(win: Window = window): SignInRefusal | null {
  const params = new URLSearchParams(win.location.search)
  const error = params.get(ERROR)
  if (!error) return null
  captured = { error, description: params.get(DESCRIPTION) ?? '' }
  win.history.replaceState(win.history.state, '', withoutRefusal(win.location.href))
  return captured
}

/** What captureSignInRefusal found at start-up, if anything. */
export function capturedSignInRefusal(): SignInRefusal | null {
  return captured
}

/** Porth's sign-out on the API host, returning to `returnTo`. */
export function porthLogoutUrl(returnTo: string): string {
  return `${authBaseUrl()}/auth/logout?return_to=${encodeURIComponent(returnTo)}`
}

/** Sign out through Porth (ending the identity provider's session too) and come back. */
export function signOutThroughPorth(returnTo: string = withoutRefusal(window.location.href)): void {
  window.location.assign(porthLogoutUrl(returnTo))
}

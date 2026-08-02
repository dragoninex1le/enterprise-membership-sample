/**
 * E2E test bypass for the BFF session (PORTH-531).
 *
 * When VITE_E2E_AUTH=true this stands in for a real login so Playwright Tier 1
 * never leaves for the IdP.
 *
 * It does NOT fake the auth context. `@estyn/porth-admin/auth` deliberately keeps
 * its React context private, and injecting a fake one would mean Tier 1 exercised
 * a different code path to production — the failure mode where the tests pass and
 * the real provider is broken. Instead it stubs the one network call the provider
 * makes (`GET /auth/me`) and renders the REAL PorthAuthProvider, so session
 * resolution, loading states and the CSRF secret all behave as they do in
 * production.
 */
import { PorthAuthProvider } from '@estyn/porth-admin/auth'
import type { ReactNode } from 'react'

const FAKE_SESSION = {
  sub: 'e2e|platform-admin',
  email: 'platform-admin@e2e.test',
  given_name: 'Platform',
  family_name: 'Admin',
  name: 'Platform Admin',
  picture: '',
  claims: {},
  // Mirrors the real /auth/me contract: api/client.ts reads this and sends it as
  // X-CSRF-Token on mutating requests.
  csrf_token: 'e2e-fake-csrf',
}

const AUTH_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

// Installed once at module load, before the provider's first effect runs.
const realFetch = globalThis.fetch.bind(globalThis)
globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  if (url.startsWith(`${AUTH_BASE}/auth/me`) || url.startsWith('/auth/me')) {
    return Promise.resolve(
      new Response(JSON.stringify(FAKE_SESSION), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  }
  return realFetch(input, init)
}

export function MockPorthAuthProvider({ children }: { children: ReactNode }) {
  return (
    <PorthAuthProvider config={{ authBaseUrl: AUTH_BASE }}>
      {children}
    </PorthAuthProvider>
  )
}

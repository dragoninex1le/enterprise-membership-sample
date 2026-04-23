/**
 * E2E test bypass for Auth0.
 *
 * When VITE_E2E_AUTH=true this provider replaces Auth0Provider and returns a
 * fake authenticated user so Playwright tests never hit the real Auth0 tenant.
 *
 * The injected user matches what mockCurrentUser() in the test helpers returns,
 * so App.tsx sees isAuthenticated=true and calls POST /users/me (which tests
 * mock via page.route).
 */
import { Auth0Context } from '@auth0/auth0-react'
import type { ReactNode } from 'react'

const FAKE_AUTH0_USER = {
  sub: 'auth0|e2e-platform-admin',
  email: 'platform-admin@e2e.test',
  given_name: 'Platform',
  family_name: 'Admin',
  name: 'Platform Admin',
  picture: '',
  email_verified: true,
  updated_at: '2024-01-01T00:00:00.000Z',
}

// Provides a minimal Auth0 context that satisfies all useAuth0() calls in the app.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ctx: any = {
  isAuthenticated: true,
  isLoading: false,
  user: FAKE_AUTH0_USER,
  error: undefined,
  loginWithRedirect: () => Promise.resolve(),
  loginWithPopup: () => Promise.resolve(),
  logout: () => Promise.resolve(),
  getAccessTokenSilently: () => Promise.resolve('e2e-fake-token'),
  getAccessTokenWithPopup: () => Promise.resolve(undefined),
  getIdTokenClaims: () => Promise.resolve(undefined),
  handleRedirectCallback: () => Promise.resolve({ appState: undefined }),
}

export function MockAuth0Provider({ children }: { children: ReactNode }) {
  return (
    <Auth0Context.Provider value={ctx}>
      {children}
    </Auth0Context.Provider>
  )
}

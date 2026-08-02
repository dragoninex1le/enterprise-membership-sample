import React from 'react'
import ReactDOM from 'react-dom/client'
import { PorthAuthProvider } from '@estyn/porth-admin/auth'
import { useTenantConfig } from './hooks/useTenantConfig'
import App from './App'
import './index.css'

// E2E test bypass: VITE_E2E_AUTH=true injects a fake authenticated session so
// Playwright Tier 1 never redirects to the IdP.
import { MockPorthAuthProvider } from './test-utils/MockPorthAuthProvider'
const E2E_AUTH = import.meta.env.VITE_E2E_AUTH === 'true'

// PORTH-531 / ADR-Z9. The /auth/* routes live on the same account-level Porth API
// as everything else (`/auth/{proxy+}` in the Porth template), so the auth base is
// the API base — there is no second host and no extra stack output. Override with
// VITE_AUTH_BASE_URL only if they ever diverge (e.g. a local proxy in dev).
const authBaseUrl =
  import.meta.env.VITE_AUTH_BASE_URL ?? import.meta.env.VITE_API_BASE_URL ?? ''

function TenantBootstrap() {
  const { config, loading, error } = useTenantConfig()

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    )
  }

  if (error || !config) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-red-600 text-sm">
          {error ?? 'Unable to load tenant configuration.'}
        </div>
      </div>
    )
  }

  if (E2E_AUTH) {
    return (
      <MockPorthAuthProvider>
        <App tenantConfig={config} />
      </MockPorthAuthProvider>
    )
  }

  // No IdP configuration is passed: the BFF owns the upstream IdP entirely and the
  // browser holds only an http-only session cookie. That is the whole point of
  // ADR-Z9 — there is no vendor SDK here to hand a domain or client_id to.
  return (
    <PorthAuthProvider config={{ authBaseUrl }}>
      <App tenantConfig={config} />
    </PorthAuthProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <TenantBootstrap />
  </React.StrictMode>,
)

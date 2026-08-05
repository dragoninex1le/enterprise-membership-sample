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

// PORTH-531 / ADR-Z9 "Path B": CloudFront routes /auth/* on the SPA's OWN host to
// the Porth API (see CacheBehaviors in template.yml), so the auth base is empty and
// the SDK calls relative /auth/login|me|logout.
//
// This is not a preference. A credentialed cross-origin fetch may not receive
// Access-Control-Allow-Origin: *, which is what Porth answers — so calling the API
// host directly is refused by the browser before the request is even sent. Serving
// the routes same-origin removes the cross-origin hop and makes the session cookie
// host-only. Override with VITE_AUTH_BASE_URL only for local dev against a proxy.
const authBaseUrl = import.meta.env.VITE_AUTH_BASE_URL ?? ''

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

import React from 'react'
import ReactDOM from 'react-dom/client'
import { Auth0Provider } from '@auth0/auth0-react'
import { useTenantConfig } from './hooks/useTenantConfig'
import App from './App'
import './index.css'

// E2E test bypass: VITE_E2E_AUTH=true skips Auth0 and injects a fake authenticated
// user so Playwright tests never redirect to the Auth0 login page.
import { MockAuth0Provider } from './test-utils/MockAuth0Provider'
const E2E_AUTH = import.meta.env.VITE_E2E_AUTH === 'true'

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
      <MockAuth0Provider>
        <App tenantConfig={config} />
      </MockAuth0Provider>
    )
  }

  return (
    <Auth0Provider
      domain={config.domain}
      clientId={config.clientId}
      authorizationParams={{
        redirect_uri: window.location.origin,
        ...(config.audience ? { audience: config.audience } : {}),
      }}
    >
      <App tenantConfig={config} />
    </Auth0Provider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <TenantBootstrap />
  </React.StrictMode>,
)

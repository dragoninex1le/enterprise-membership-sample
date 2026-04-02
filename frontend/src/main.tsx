import React from 'react'
import ReactDOM from 'react-dom/client'
import { Auth0Provider } from '@auth0/auth0-react'
import { useTenantConfig } from './hooks/useTenantConfig'
import App from './App'
import './index.css'

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

  return (
    <Auth0Provider
      domain={config.domain}
      clientId={config.clientId}
      authorizationParams={{
        redirect_uri: window.location.origin,
        ...(config.audience ? { audience: config.audience } : {}),
      }}
    >
      <App />
    </Auth0Provider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <TenantBootstrap />
  </React.StrictMode>,
)

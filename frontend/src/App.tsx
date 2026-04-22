import { useAuth0 } from '@auth0/auth0-react'
import { RouterProvider } from 'react-router-dom'
import { useEffect } from 'react'
import { router } from './router'
import { setTokenProvider } from './api/client'
import { useCurrentUser } from './hooks/useCurrentUser'
import { PorthProvider } from './context/PorthContext'
import type { TenantIdpConfig } from './hooks/useTenantConfig'

interface Props {
  tenantConfig: TenantIdpConfig
}

export default function App({ tenantConfig }: Props) {
  const { isLoading, error, isAuthenticated, getAccessTokenSilently } = useAuth0()
  const { currentUser, loading: userLoading, error: userError } = useCurrentUser(tenantConfig)

  // Wire Auth0 token into the API client so all API calls are authenticated
  useEffect(() => {
    if (isAuthenticated) {
      setTokenProvider(getAccessTokenSilently)
    }
  }, [isAuthenticated, getAccessTokenSilently])

  if (isLoading || (isAuthenticated && userLoading)) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-red-600 text-sm">Auth error: {error.message}</div>
      </div>
    )
  }

  return (
    <PorthProvider
      tenantConfig={tenantConfig}
      currentUser={currentUser}
      userLoading={userLoading}
      userError={userError}
    >
      <RouterProvider router={router} />
    </PorthProvider>
  )
}

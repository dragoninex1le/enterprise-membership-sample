import { useAuth } from '@estyn/porth-admin/auth'
import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { useCurrentUser } from './hooks/useCurrentUser'
import { PorthProvider } from './context/PorthContext'
import type { TenantConfig } from './hooks/useTenantConfig'

interface Props {
  tenantConfig: TenantConfig
}

export default function App({ tenantConfig }: Props) {
  // PORTH-531: no token wiring. Under the BFF the browser holds no token, so
  // there is nothing to inject into the API clients — they authenticate with the
  // http-only session cookie (see api/client.ts), and the previous
  // setTokenProvider / setSampleTokenProvider plumbing is gone.
  const { isLoading, error, isAuthenticated } = useAuth()
  const { currentUser, loading: userLoading, error: userError } = useCurrentUser(tenantConfig)

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

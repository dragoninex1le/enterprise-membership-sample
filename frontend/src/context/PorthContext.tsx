import { createContext, useContext, type ReactNode } from 'react'
import type { TenantIdpConfig } from '../hooks/useTenantConfig'
import type { CurrentUser } from '../hooks/useCurrentUser'

interface PorthContextValue {
  tenantConfig: TenantIdpConfig
  currentUser: CurrentUser | null
  userLoading: boolean
  userError: string | null
}

const PorthContext = createContext<PorthContextValue | null>(null)

export function usePorthContext(): PorthContextValue {
  const ctx = useContext(PorthContext)
  if (!ctx) throw new Error('usePorthContext must be used within PorthProvider')
  return ctx
}

export function PorthProvider({
  tenantConfig,
  currentUser,
  userLoading,
  userError,
  children,
}: PorthContextValue & { children: ReactNode }) {
  return (
    <PorthContext.Provider value={{ tenantConfig, currentUser, userLoading, userError }}>
      {children}
    </PorthContext.Provider>
  )
}

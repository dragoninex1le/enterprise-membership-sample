import { useState, useEffect } from 'react'
import { useAuth } from '@estyn/porth-admin/auth'
import { usersApi } from '../api/users'
import type { User, Role } from '../api/types'
import type { TenantConfig } from './useTenantConfig'

export interface CurrentUser {
  porthUser: User
  roles: Role[]
  permissions: string[]
}

/**
 * PORTH-413 / PORTH-531 (cookie mode): identity comes from the BFF session via
 * `useAuth().user` — a vendor-neutral profile resolved server-side — rather than
 * from an IdP hook. Once the session resolves, provisions the user in Porth via
 * POST /users/me (authenticated by the http-only session cookie) and returns the
 * resolved user + roles + permissions in one call.
 *
 * Per the Porth architecture (Confluence: Architecture: User Management &
 * Multi-Tenancy), provisioning and role resolution are backend concerns handled
 * by DirectorMiddleware. This hook is the frontend integration point.
 */
export function useCurrentUser(tenantConfig: TenantConfig | null): {
  currentUser: CurrentUser | null
  loading: boolean
  error: string | null
} {
  const { user, isAuthenticated, isLoading: authLoading } = useAuth()
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // While the session is still resolving, keep loading true so ProtectedRoute
    // never sees userLoading=false with currentUser=null. Without this guard the
    // initial fire (isAuthenticated=false) sets loading=false immediately, and
    // ProtectedRoute evaluates useHasRole against a null currentUser and
    // redirects to /unauthorized before provisioning completes.
    if (authLoading) return

    if (!isAuthenticated || !user || !tenantConfig) {
      setLoading(false)
      return
    }

    // sub and email are non-optional on the Porth side; a missing value would
    // produce an invalid upsert payload and a confusing 4xx rather than a clear
    // UI message.
    if (!user.sub || !user.email) {
      setError('Session profile is missing sub or email — cannot provision user.')
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)
    setCurrentUser(null)

    // Single call: provision (upsert profile + sync claim-resolved roles) and
    // return the full user context atomically. Namespaced role claims ride on
    // `user.claims` and are forwarded as jwt_claims for the Porth claim-resolver
    // — only roles in the current tenant's ClaimMappingConfig are synced, so
    // roles for other tenants are never affected. external_id / tenant_id /
    // organization_id are derived server-side and must NOT be sent.
    usersApi
      .me({
        email: user.email,
        jwt_claims: (user.claims ?? {}) as Record<string, unknown>,
        first_name: user.givenName,
        last_name: user.familyName,
        display_name: user.name,
        avatar_url: user.picture,
      })
      .then(({ user: porthUser, roles, permissions }) => setCurrentUser({ porthUser, roles, permissions }))
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [authLoading, isAuthenticated, user, tenantConfig])

  return { currentUser, loading, error }
}

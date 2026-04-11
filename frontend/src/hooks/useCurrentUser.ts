import { useState, useEffect } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { usersApi } from '../api/users'
import type { User, Role } from '../api/types'
import type { TenantIdpConfig } from './useTenantConfig'

export interface CurrentUser {
  porthUser: User
  roles: Role[]
}

/**
 * PORTH-413: Provisions the current user in Porth on login and fetches their
 * full Porth context (user record + resolved roles + effective permissions) in
 * a single POST /users/me call.
 *
 * POST /users/me replaces the previous two-step provision + getUserRoles
 * pattern: it upserts the user record, syncs JWT claim-resolved roles to
 * DynamoDB, then returns user + roles + permissions in one response — so the
 * SPA is never in a state where the user record exists but roles haven't
 * loaded yet.
 *
 * Per the Porth architecture (Confluence: Architecture: User Management &
 * Multi-Tenancy), user provisioning and role resolution are backend concerns
 * handled by DirectorMiddleware. This hook is the frontend integration point
 * that triggers provisioning and surfaces the resolved UserContext.
 */
export function useCurrentUser(tenantConfig: TenantIdpConfig | null): {
  currentUser: CurrentUser | null
  loading: boolean
  error: string | null
} {
  const { user: auth0User, isAuthenticated, isLoading: auth0Loading } = useAuth0()
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // While Auth0 is still resolving the session, keep our loading flag true
    // so ProtectedRoute never sees userLoading=false with currentUser=null.
    // Without this guard the initial effect fire (isAuthenticated=false) would
    // set loading=false immediately, and by the time Auth0 flips isAuthenticated
    // the ProtectedRoute would evaluate useHasRole against a null currentUser
    // and redirect to /unauthorized before provisioning completes.
    if (auth0Loading) return

    if (!isAuthenticated || !auth0User || !tenantConfig) {
      // Auth0 has finished and the user is definitely not authenticated
      // (or required config is absent) — nothing left to do.
      setLoading(false)
      return
    }

    // Validate required IdP fields before hitting the API — sub and email are
    // non-optional on the Porth side; a missing value would produce an invalid
    // upsert payload and a confusing 4xx error rather than a clear UI message.
    if (!auth0User.sub || !auth0User.email) {
      setError('Auth0 user profile is missing required fields (sub or email). Cannot provision user.')
      setLoading(false)
      return
    }

    // Signal that provisioning is in-flight so ProtectedRoute continues to
    // show the loading state rather than evaluating roles against a null user.
    setLoading(true)
    setError(null)
    setCurrentUser(null)

    // Single call: provision (upsert profile + sync JWT claim-resolved roles)
    // and return the full user context atomically.  The full Auth0 user object
    // is passed as jwt_claims so the Porth claim-resolver can map IdP claims
    // to Porth roles — only roles in the *current tenant's* ClaimMappingConfig
    // are synced, so tenant-specific application roles for other tenants are
    // never affected.
    usersApi
      .me({
        email: auth0User.email,
        // Pass the full decoded Auth0 user object as jwt_claims.  Custom
        // namespaced claims (e.g. https://porth.io/roles) are included here.
        // external_id, tenant_id, organization_id are derived from the JWT
        // by the server — they must NOT be sent in the request body.
        jwt_claims: auth0User as Record<string, unknown>,
        first_name: auth0User.given_name,
        last_name: auth0User.family_name,
        display_name: auth0User.name,
        avatar_url: auth0User.picture,
      })
      .then(({ user: porthUser, roles }) => setCurrentUser({ porthUser, roles }))
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [auth0Loading, isAuthenticated, auth0User, tenantConfig])

  return { currentUser, loading, error }
}

import { useState, useEffect } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { usersApi } from '../api/users'
import { rolesApi } from '../api/roles'
import type { User, Role } from '../api/types'
import type { TenantIdpConfig } from './useTenantConfig'

export interface CurrentUser {
  porthUser: User
  roles: Role[]
}

/**
 * Provisions the current user in Porth on login (upsert) and fetches their
 * assigned Porth roles from the API.
 *
 * Per the Porth architecture (Confluence: Architecture: User Management &
 * Multi-Tenancy), user provisioning and role resolution are backend concerns
 * handled by DirectorMiddleware. This hook is the frontend integration point
 * that triggers provisioning and surfaces the resolved UserContext.
 *
 * TODO (PORTH-413): Once the Porth API exposes GET /users/me returning a full
 * UserContext (user + role_keys + permissions), replace the upsert +
 * getUserRoles two-step here with a single GET /users/me call.
 */
export function useCurrentUser(tenantConfig: TenantIdpConfig | null): {
  currentUser: CurrentUser | null
  loading: boolean
  error: string | null
} {
  const { user: auth0User, isAuthenticated } = useAuth0()
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isAuthenticated || !auth0User || !tenantConfig) {
      setLoading(false)
      return
    }

    const { tenantId, organizationId } = tenantConfig

    // Provision (upsert) the user in Porth, then fetch their assigned roles.
    // The upsert creates the user record on first login and keeps profile
    // fields (email, name, avatar) in sync with the IdP on subsequent logins.
    usersApi
      .upsert({
        external_id: auth0User.sub!,
        email: auth0User.email!,
        organization_id: organizationId,
        tenant_id: tenantId,
        first_name: auth0User.given_name,
        last_name: auth0User.family_name,
        display_name: auth0User.name,
        avatar_url: auth0User.picture,
      })
      .then(porthUser =>
        rolesApi
          .getUserRoles(porthUser.id, tenantId)
          .then(roles => setCurrentUser({ porthUser, roles }))
      )
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [isAuthenticated, auth0User, tenantConfig])

  return { currentUser, loading, error }
}

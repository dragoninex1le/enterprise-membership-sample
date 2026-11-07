import { useMatch, useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from './useRoles'
import { PLATFORM_ADMIN } from '../constants'

/** The platform tenant: written by the Porth install, not managed from this UI. */
export const PLATFORM_TENANT_ID = 'platform'

/** The tenant-page route a platform admin manages a tenant under. */
export const TENANT_PAGE = '/admin/platform/tenants/:tenantId/*'

export function tenantPagePath(tenantId: string, section: 'roles' | 'claim-mapping' = 'roles'): string {
  return `/admin/platform/tenants/${encodeURIComponent(tenantId)}/${section}`
}

/**
 * The tenant an admin screen is about.
 *
 * A platform admin manages a tenant they have CHOSEN, from its tenant page
 * (/admin/platform/tenants/:tenantId/...). There is no fallback to their own
 * tenant: an empty answer means none is chosen, and the screen says so rather
 * than quietly showing the platform tenant as if it were the one being managed.
 *
 * A tenant admin manages their own tenant, always.
 */
export function useManagedTenant(): string {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const match = useMatch(TENANT_PAGE)
  const [searchParams] = useSearchParams()
  if (isPlatformAdmin) {
    return match?.params.tenantId ?? searchParams.get('tenantId') ?? ''
  }
  return currentUser?.porthUser.tenant_id ?? ''
}

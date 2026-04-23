import { usePorthContext } from '../context/PorthContext'

/**
 * Returns the Porth role names held by the current user, sourced from the
 * Porth API via useCurrentUser. Role names are tenant-configured strings —
 * they are NOT a hardcoded enum in the frontend.
 *
 * For Estyn platform operators the role is 'platform-admin'.
 * For tenant-level users, roles are whatever the tenant has configured
 * in their claim role mappings (e.g. 'viewer', 'ar_clerk', 'ap_clerk',
 * 'controller').
 */
export function useRoles(): string[] {
  const { currentUser } = usePorthContext()
  return currentUser?.roles.map(r => r.name) ?? []
}

export function useHasRole(...roles: string[]): boolean {
  const userRoles = useRoles()
  return roles.some(r => userRoles.includes(r))
}

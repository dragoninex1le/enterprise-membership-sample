import { useAuth0 } from '@auth0/auth0-react'

// Auth0 custom claim namespace — roles are embedded here in the JWT
const ROLES_CLAIM = 'https://porth.io/roles'

export type AppRole = 'viewer' | 'ar_clerk' | 'ap_clerk' | 'controller' | 'admin'

export function useRoles(): AppRole[] {
  const { user } = useAuth0()
  if (!user) return []
  const raw = user[ROLES_CLAIM]
  if (!Array.isArray(raw)) return []
  return raw as AppRole[]
}

export function useHasRole(...roles: AppRole[]): boolean {
  const userRoles = useRoles()
  return roles.some(r => userRoles.includes(r))
}

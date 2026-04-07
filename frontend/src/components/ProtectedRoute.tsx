import { Navigate, Outlet } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { useHasRole } from '../hooks/useRoles'

interface Props {
  // Role names are tenant-configured strings, not a fixed enum.
  // Platform operator role: 'platform-admin'
  // Tenant user roles: configured per-tenant (e.g. 'viewer', 'ar_clerk')
  roles: string[]
}

export default function ProtectedRoute({ roles }: Props) {
  const { isAuthenticated, isLoading } = useAuth0()
  const allowed = useHasRole(...roles)

  if (isLoading) return null
  if (!isAuthenticated) return <Navigate to="/" replace />
  if (!allowed) return <Navigate to="/unauthorized" replace />

  return <Outlet />
}

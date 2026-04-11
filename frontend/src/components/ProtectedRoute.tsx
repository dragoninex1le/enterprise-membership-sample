import { Navigate, Outlet } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'

interface Props {
  // Role names are tenant-configured strings, not a fixed enum.
  // Platform operator role: 'platform-admin'
  // Tenant user roles: configured per-tenant (e.g. 'viewer', 'ar_clerk')
  roles: string[]
}

export default function ProtectedRoute({ roles }: Props) {
  const { isAuthenticated, isLoading: auth0Loading } = useAuth0()
  // Wait for the Porth user (provision + role-fetch) to complete before
  // making access decisions — without this guard, the route redirects to
  // /unauthorized before currentUser is populated, and the user gets stuck.
  const { userLoading } = usePorthContext()
  const allowed = useHasRole(...roles)

  if (auth0Loading || userLoading) return null
  if (!isAuthenticated) return <Navigate to="/" replace />
  if (!allowed) return <Navigate to="/unauthorized" replace />

  return <Outlet />
}

import { Navigate, Outlet } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import { useHasRole, type AppRole } from '../hooks/useRoles'

interface Props {
  roles: AppRole[]
}

export default function ProtectedRoute({ roles }: Props) {
  const { isAuthenticated, isLoading } = useAuth0()
  const allowed = useHasRole(...roles)

  if (isLoading) return null
  if (!isAuthenticated) return <Navigate to="/" replace />
  if (!allowed) return <Navigate to="/unauthorized" replace />

  return <Outlet />
}

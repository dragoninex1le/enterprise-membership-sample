import { createBrowserRouter, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { useHasRole } from './hooks/useRoles'
import { PLATFORM_ADMIN, SAMPLE_ROLES } from './constants'

const { TENANT_ADMIN, VIEWER, AR_CLERK, AP_CLERK, CONTROLLER } = SAMPLE_ROLES

/** Redirects the root path based on the caller's highest role.
 *  Platform admins → org management; tenant admins → tenant management;
 *  everyone else → dashboard. */
function RootRedirect() {
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const isTenantAdmin = useHasRole(SAMPLE_ROLES.TENANT_ADMIN)
  if (isPlatformAdmin) return <Navigate to="/admin/platform/organizations" replace />
  if (isTenantAdmin)   return <Navigate to="/admin/tenant/users" replace />
  return <Navigate to="/dashboard" replace />
}
import DashboardPage from './pages/DashboardPage'
import ARPage from './pages/ARPage'
import APPage from './pages/APPage'
import ApprovalsPage from './pages/ApprovalsPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
import OrganizationsPage from './pages/OrganizationsPage'
import TenantsPage from './pages/TenantsPage'
import UsersPage from './pages/UsersPage'
import RolesPage from './pages/RolesPage'
import PermissionsPage from './pages/PermissionsPage'
import ClaimMappingConfigPage from './pages/ClaimMappingConfigPage'
import ClaimRoleMappingPage from './pages/ClaimRoleMappingPage'


export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <RootRedirect /> },

      // ── Functional areas ──────────────────────────────────────────────────
      {
        element: <ProtectedRoute roles={[VIEWER, AR_CLERK, AP_CLERK, CONTROLLER, TENANT_ADMIN, PLATFORM_ADMIN]} />,
        children: [
          { path: 'dashboard', element: <DashboardPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={[AR_CLERK, CONTROLLER, TENANT_ADMIN, PLATFORM_ADMIN]} />,
        children: [
          { path: 'ar', element: <ARPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={[AP_CLERK, CONTROLLER, TENANT_ADMIN, PLATFORM_ADMIN]} />,
        children: [
          { path: 'ap', element: <APPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={[CONTROLLER, TENANT_ADMIN, PLATFORM_ADMIN]} />,
        children: [
          { path: 'approvals', element: <ApprovalsPage /> },
        ],
      },

      // ── Platform admin (Estyn operators — org/tenant onboarding) ──────────
      {
        path: 'admin/platform',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="organizations" replace /> },
          { path: 'organizations', element: <OrganizationsPage /> },
          { path: 'organizations/:orgId/tenants', element: <TenantsPage /> },
        ],
      },

      // ── Tenant admin (local admin — users, roles, permissions) ────────────
      {
        path: 'admin/tenant',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN, SAMPLE_ROLES.TENANT_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="users" replace /> },
          { path: 'users', element: <UsersPage /> },
          { path: 'roles', element: <RolesPage /> },
          { path: 'permissions', element: <PermissionsPage /> },
          { path: 'claim-config', element: <ClaimMappingConfigPage /> },
          { path: 'claim-mappings', element: <ClaimRoleMappingPage /> },
        ],
      },
    ],
  },
  { path: '/unauthorized', element: <UnauthorizedPage /> },
])

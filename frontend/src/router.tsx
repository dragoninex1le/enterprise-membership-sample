import { createBrowserRouter, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { useHasRole } from './hooks/useRoles'

/** Redirects the root path based on the caller's role. Platform admins land on
 *  the organisations page; everyone else goes to the dashboard. */
function RootRedirect() {
  const isPlatformAdmin = useHasRole('platform-admin')
  return isPlatformAdmin
    ? <Navigate to="/admin/platform/organizations" replace />
    : <Navigate to="/dashboard" replace />
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

// Role name constants — these must match what the Porth bootstrap creates and
// what the IdP Action injects into the JWT via the claim mapping.
// Tenant-level roles (viewer, ar_clerk, etc.) are sample-app roles configured
// in claim role mappings — they are NOT hardcoded platform roles.
const PLATFORM_ADMIN = 'platform-admin'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <RootRedirect /> },

      // ── Functional areas ──────────────────────────────────────────────────
      // These routes use tenant-configured role names from claim role mappings.
      // platform-admin is included so Estyn operators can access the sample app.
      {
        element: <ProtectedRoute roles={['viewer', 'ar_clerk', 'ap_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [
          { path: 'dashboard', element: <DashboardPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['ar_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [
          { path: 'ar', element: <ARPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['ap_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [
          { path: 'ap', element: <APPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['controller', PLATFORM_ADMIN]} />,
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
        element: <ProtectedRoute roles={[PLATFORM_ADMIN]} />,
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

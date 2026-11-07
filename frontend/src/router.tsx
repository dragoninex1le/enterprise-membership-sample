import { createBrowserRouter, Navigate, useSearchParams } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { useHasRole } from './hooks/useRoles'
import { PLATFORM_ADMIN, SAMPLE_ROLES } from './constants'

const { TENANT_ADMIN, VIEWER, AR_CLERK, AP_CLERK, CONTROLLER } = SAMPLE_ROLES

function RootRedirect() {
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const isTenantAdmin = useHasRole(SAMPLE_ROLES.TENANT_ADMIN)
  if (isPlatformAdmin) return <Navigate to="/admin/platform/tenants" replace />
  if (isTenantAdmin) return <Navigate to="/admin/tenant/roles" replace />
  return <Navigate to="/dashboard" replace />
}

import DashboardPage from './pages/DashboardPage'
import ARPage from './pages/ARPage'
import APPage from './pages/APPage'
import ApprovalsPage from './pages/ApprovalsPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
import OrganizationsPage from './pages/OrganizationsPage'
import TenantsPage from './pages/TenantsPage'
import ClaimMappingConfigPage from './pages/ClaimMappingConfigPage'
import TenantPage from './pages/TenantPage'
import { tenantPagePath } from './hooks/useManagedTenant'
import PermissionsPage from './pages/PermissionsPage'
import UsersPage from './pages/UsersPage'
import RolesPage from './pages/RolesPage'

/**
 * /admin/tenant/{roles,claim-config} are a tenant admin's own screens. A platform admin manages a
 * tenant from that tenant's page, so on these paths they are sent there - or to Tenants to choose
 * one - rather than shown a screen about no tenant in particular.
 */
function TenantScreen({ section, children }: { section: 'roles' | 'claim-mapping'; children: JSX.Element }) {
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const [searchParams] = useSearchParams()
  if (!isPlatformAdmin) return children
  const tenantId = searchParams.get('tenantId')
  return <Navigate to={tenantId ? tenantPagePath(tenantId, section) : '/admin/platform/tenants'} replace />
}

/** The token tester now sits under the claim mapping editor. */
function ClaimMappingsMoved() {
  const [searchParams] = useSearchParams()
  const query = searchParams.toString()
  return <Navigate to={`/admin/tenant/claim-config${query ? `?${query}` : ''}`} replace />
}

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

      // ── Platform admin ─────────────────────────────────────────────────────────
      {
        path: 'admin/platform',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="tenants" replace /> },
          { path: 'tenants', element: <TenantsPage /> },
          {
            path: 'tenants/:tenantId',
            element: <TenantPage />,
            children: [
              { index: true, element: <Navigate to="roles" replace /> },
              { path: 'roles', element: <RolesPage /> },
              { path: 'claim-mapping', element: <ClaimMappingConfigPage /> },
            ],
          },
          // legacy redirect
          { path: 'organizations', element: <OrganizationsPage /> },
          { path: 'organizations/:orgId/tenants', element: <Navigate to="/admin/platform/tenants" replace /> },
        ],
      },

      // ── Tenant admin ──────────────────────────────────────────────────────────
      {
        path: 'admin/tenant',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN, SAMPLE_ROLES.TENANT_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="roles" replace /> },
          { path: 'roles', element: <TenantScreen section="roles"><RolesPage /></TenantScreen> },
          { path: 'claim-config', element: <TenantScreen section="claim-mapping"><ClaimMappingConfigPage /></TenantScreen> },
          { path: 'claim-mappings', element: <ClaimMappingsMoved /> },
          { path: 'permissions', element: <PermissionsPage /> },
          { path: 'users', element: <UsersPage /> },
        ],
      },
    ],
  },
  { path: '/unauthorized', element: <UnauthorizedPage /> },
])
